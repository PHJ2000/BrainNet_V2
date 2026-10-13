package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceInput.*;
import static com.brainnet.spring.WorkspaceInput.map;
import static com.brainnet.spring.WorkspaceViews.*;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.*;
import java.util.*;

@Service
class NodeOperationService {
    private final ProjectAccessService access;
    private final NodeOutboxService outbox;

    final WorkspaceRepository repository;
    final NodeHistoryService history;
    final NodeMetricsService metrics;
    final ActivityService activity;

    NodeOperationService(
            ProjectAccessService access,
            NodeOutboxService outbox,
            WorkspaceRepository repository,
            NodeHistoryService history,
            NodeMetricsService metrics,
            ActivityService activity) {
        this.access = access;
        this.outbox = outbox;

        this.repository = repository;
        this.history = history;
        this.metrics = metrics;
        this.activity = activity;
    }

    Map<String, Object> snapshot(long pid, List<Long> ids) {
        String placeholders = String.join(",", Collections.nCopies(ids.size(), "?"));
        if (ids.isEmpty())
            return Map.of("nodes", List.of(), "tag_nodes", List.of(), "versions", List.of());
        var args = new ArrayList<Object>();
        args.add(pid);
        args.addAll(ids);
        var data = new LinkedHashMap<String, Object>();
        data.put(
                "nodes",
                repository.rows(
                        "SELECT * FROM node WHERE project_id=? AND id IN ("
                                + placeholders
                                + ") ORDER BY id",
                        args.toArray()));
        data.put(
                "tag_nodes",
                repository.rows(
                        "SELECT * FROM tag_node WHERE node_id IN ("
                                + placeholders
                                + ") ORDER BY node_id,tag_id",
                        ids.toArray()));
        data.put(
                "versions",
                repository.rows(
                        "SELECT * FROM node_version WHERE node_id IN ("
                                + placeholders
                                + ") ORDER BY node_id,version_no",
                        ids.toArray()));
        return data;
    }

    // Metrics are a derived cache. Ignore them in legacy snapshots as well as new ones.
    private Map<String, Object> conflictSnapshot(Object snapshot) {
        var relevant = new LinkedHashMap<>(map(snapshot));
        relevant.remove("metrics");
        return relevant;
    }

    Map<String, Object> scope(long pid, long node) {
        repository.node(pid, node);
        var ids =
                repository
                        .rows(
                                "WITH RECURSIVE tree AS(SELECT id FROM node WHERE project_id=? AND"
                                    + " id=? UNION SELECT n.id FROM node n JOIN tree t ON"
                                    + " n.parent_id=t.id WHERE n.project_id=?) SELECT n.id FROM"
                                    + " node n JOIN tree t ON t.id=n.id ORDER BY n.id FOR UPDATE OF"
                                    + " n",
                                pid,
                                node,
                                pid)
                        .stream()
                        .map(r -> number(r.get("id")))
                        .toList();
        return snapshot(pid, ids);
    }

    String record(
            long pid,
            long uid,
            long node,
            String kind,
            Map<String, Object> before,
            Map<String, Object> after,
            String key,
            Object request,
            Object response) {
        String id = UUID.randomUUID().toString();
        repository.db.update(
                "INSERT INTO"
                    + " node_operation(id,project_id,actor_id,node_id,kind,request_key,request_hash,\"before\",\"after\",response,created_at,expires_at)"
                    + " VALUES(?,?,?,?,?,?,?,?::jsonb,?::jsonb,?::jsonb,now(),now()+interval '30"
                    + " days')",
                id,
                pid,
                uid,
                node,
                kind,
                key,
                request == null ? null : repository.hash(request),
                repository.encode(before),
                repository.encode(after),
                response == null ? null : repository.encode(response));
        return id;
    }

    void created(long pid, long uid, long node) {
        record(pid, uid, node, "create", Map.of(), snapshot(pid, List.of(node)), null, null, null);
    }

    record Replay(tools.jackson.databind.JsonNode response) {}

    Replay replay(long pid, long uid, String key, Object request) {
        if (key == null) return null;
        if (key.isBlank() || key.length() > 128)
            throw fail(422, "IDEMPOTENCY_KEY_INVALID", "Invalid request key");
        repository.db.queryForObject(
                "SELECT pg_advisory_xact_lock(hashtextextended(?,0))",
                Object.class,
                "operation:" + pid + ":" + uid + ":" + key);
        var old =
                repository.one(
                        "SELECT * FROM node_operation WHERE project_id=? AND actor_id=? AND"
                                + " request_key=?",
                        pid,
                        uid,
                        key);
        if (old != null) {
            if (!repository.hash(request).equals(old.get("request_hash")))
                throw fail(409, "IDEMPOTENCY_KEY_REUSED", "Request key belongs to another command");
            if (expired(old)) throw fail(410, "OPERATION_EXPIRED", "Replay expired");
        }
        return old == null ? null : new Replay(repository.json.valueToTree(old.get("response")));
    }

    boolean expired(Map<String, Object> r) {
        return Instant.parse(str(r.get("expires_at"))).isBefore(Instant.now());
    }

    Map<String, Object> summary(Map<String, Object> r, long uid) {
        var out =
                WorkspaceInput.pick(
                        r,
                        "id",
                        "node_id",
                        "kind",
                        "actor_id",
                        "created_at",
                        "expires_at",
                        "undone_by");
        out.put("expired", expired(r));
        out.put(
                "can_undo",
                !expired(r)
                        && r.get("undone_by") == null
                        && !"undo".equals(r.get("kind"))
                        && r.get("actor_id") != null
                        && number(r.get("actor_id")) == uid);
        var before = map(r.get("before"));
        var saved = before.containsKey("nodes") ? before : map(r.get("after"));
        out.put("node_count", ((List<?>) saved.getOrDefault("nodes", List.of())).size());
        return out;
    }

    Page<Operation, String> list(long pid, long uid, String before, int limit) {
        access.member(pid, uid);
        long sequence =
                before == null
                        ? Long.MAX_VALUE
                        : number(repository.item("node_operation", pid, before).get("sequence"));
        var rows =
                repository.rows(
                        "SELECT * FROM node_operation WHERE project_id=? AND sequence<? ORDER BY"
                                + " sequence DESC LIMIT ?",
                        pid,
                        sequence,
                        limit + 1);
        var items =
                rows.stream()
                        .limit(limit)
                        .map(row -> repository.view(summary(row, uid), Operation.class))
                        .toList();
        return new Page<>(items, rows.size() > limit ? items.getLast().id() : null);
    }

    void check(Map<String, Object> r, long uid) {
        if (r.get("actor_id") == null || number(r.get("actor_id")) != uid)
            throw fail(403, "OPERATION_FORBIDDEN", "Only your own operation can be undone");
        if (expired(r)) throw fail(410, "OPERATION_EXPIRED", "Recovery expired after 30 days");
        if (r.get("undone_by") != null || "undo".equals(r.get("kind")))
            throw fail(409, "OPERATION_ALREADY_UNDONE", "Operation cannot be undone");
    }

    Map<String, Object> validate(Map<String, Object> r) {
        long pid = number(r.get("project_id")), node = number(r.get("node_id"));
        String kind = str(r.get("kind"));
        if (kind.equals("update") || kind.equals("create")) {
            var current = kind.equals("create") ? scope(pid, node) : snapshot(pid, List.of(node));
            if (!repository.hash(current).equals(repository.hash(conflictSnapshot(r.get("after")))))
                throw fail(409, "OPERATION_CONFLICT", "Node or attached data changed");
            return current;
        }
        if (!kind.equals("delete"))
            throw fail(409, "OPERATION_UNSUPPORTED", "Unsupported operation");
        var saved = map(r.get("before"));
        var nodes = objects(saved.get("nodes"), 5000);
        var ids = new HashSet<Long>();
        for (var n : nodes) {
            long id = number(n.get("id"));
            ids.add(id);
            if (repository.one("SELECT id FROM node WHERE id=?", id) != null)
                throw fail(409, "OPERATION_CONFLICT", "Deleted ID is already present");
        }
        var parents = map(saved.getOrDefault("parent_versions", Map.of()));
        for (var e : parents.entrySet()) {
            var p =
                    repository.one(
                            "SELECT version FROM node WHERE project_id=? AND id=? FOR UPDATE",
                            pid,
                            Long.parseLong(e.getKey()));
            if (p == null || number(p.get("version")) != number(e.getValue()))
                throw fail(409, "OPERATION_CONFLICT", "Parent changed after deletion");
        }
        for (var tag : objects(saved.getOrDefault("tags", List.of()), 5000)) {
            var now =
                    repository.one(
                            "SELECT * FROM tag WHERE project_id=? AND id=? FOR UPDATE",
                            pid,
                            tag.get("id"));
            if (now == null || !repository.hash(now).equals(repository.hash(tag)))
                throw fail(409, "OPERATION_CONFLICT", "Required tag changed");
        }
        var authors = new HashSet<Long>();
        for (var n : nodes) if (n.get("author_id") != null) authors.add(number(n.get("author_id")));
        for (var v : objects(saved.get("versions"), 100000))
            if (v.get("author_id") != null) authors.add(number(v.get("author_id")));
        for (long author : authors)
            if (repository.one("SELECT id FROM app_user WHERE id=? FOR KEY SHARE", author) == null)
                throw fail(409, "OPERATION_CONFLICT", "Original author no longer exists");
        if (nodes.stream()
                        .anyMatch(
                                n -> n.get("parent_id") == null && "ACTIVE".equals(n.get("state")))
                && repository.one(
                                "SELECT id FROM node WHERE project_id=? AND parent_id IS NULL AND"
                                        + " state='ACTIVE'",
                                pid)
                        != null)
            throw fail(409, "ROOT_NODE_CONFLICT", "Another active root exists");
        return Map.of();
    }

    @Transactional
    public OperationPreview preview(long pid, long uid, String id) {
        access.lock(pid, uid, false);
        var r = repository.item("node_operation", pid, id);
        check(r, uid);
        var current = validate(r);
        var out = summary(r, uid);
        out.put("before", r.get("before"));
        out.put("after", r.get("after"));
        out.put(
                "preview_hash",
                repository.hash(
                        List.of(
                                id,
                                conflictSnapshot(r.get("before")),
                                conflictSnapshot(r.get("after")),
                                current)));
        return repository.view(out, OperationPreview.class);
    }

    @Transactional
    public DeletePreview deletePreview(long pid, long uid, long node) {
        access.lock(pid, uid, false);
        var saved = scope(pid, node);
        var target =
                objects(saved.get("nodes"), 5000).stream()
                        .filter(n -> number(n.get("id")) == node)
                        .findFirst()
                        .orElseThrow();
        return new DeletePreview(
                objects(saved.get("nodes"), 5000).stream()
                        .map(
                                row ->
                                        repository.json
                                                .<tools.jackson.databind.JsonNode>valueToTree(row))
                        .toList(),
                ((List<?>) saved.get("nodes")).size(),
                number(target.get("version")),
                repository.hash(saved));
    }

    @Transactional
    public void delete(
            long pid, long uid, long node, Integer expected, String scopeHash, String key) {
        access.lock(pid, uid, true);
        var request = new ArrayList<Object>();
        Collections.addAll(request, "delete", node, expected, scopeHash);
        if (replay(pid, uid, key, request) != null) return;
        var before = scope(pid, node);
        var nodes = objects(before.get("nodes"), 5000);
        var target =
                nodes.stream().filter(n -> number(n.get("id")) == node).findFirst().orElseThrow();
        if (expected != null && number(target.get("version")) != expected)
            throw fail(409, "NODE_VERSION_CONFLICT", "Node changed");
        if (scopeHash != null && !scopeHash.equals(repository.hash(before)))
            throw fail(409, "OPERATION_CONFLICT", "Delete preview is stale");
        var ids =
                nodes.stream()
                        .map(n -> number(n.get("id")))
                        .collect(java.util.stream.Collectors.toSet());
        var parents = new TreeMap<String, Object>();
        for (var n : nodes)
            if (n.get("parent_id") != null && !ids.contains(number(n.get("parent_id")))) {
                var p =
                        repository.one(
                                "SELECT id,version FROM node WHERE project_id=? AND id=? FOR"
                                        + " UPDATE",
                                pid,
                                n.get("parent_id"));
                parents.put(str(p.get("id")), p.get("version"));
            }
        before.put("parent_versions", parents);
        var tags = new TreeSet<Long>();
        for (var t : objects(before.get("tag_nodes"), 50000)) tags.add(number(t.get("tag_id")));
        var savedTags = new ArrayList<Map<String, Object>>();
        for (long tag : tags)
            savedTags.add(
                    repository.one(
                            "SELECT * FROM tag WHERE project_id=? AND id=? FOR UPDATE", pid, tag));
        before.put("tags", savedTags);
        repository.db.update(
                "DELETE FROM node WHERE id IN ("
                        + String.join(",", Collections.nCopies(ids.size(), "?"))
                        + ")",
                ids.toArray());
        record(pid, uid, node, "delete", before, Map.of(), key, request, Map.of());
        metrics.invalidate(pid);
        activity.append(
                pid, uid, "NODE_DELETE", Map.of("node_id", node, "deleted_count", nodes.size()));
        outbox.append(pid, node, "node.deleted", Map.of());
    }

    void restoreRows(String table, List<Map<String, Object>> rows) {
        for (var row : rows)
            repository.db.update(
                    "INSERT INTO "
                            + table
                            + " SELECT * FROM jsonb_populate_record(NULL::"
                            + table
                            + ",?::jsonb)",
                    repository.encode(row));
    }

    @Transactional
    public UndoResult undo(long pid, long uid, String id, String key, String hash) {
        access.lock(pid, uid, true);
        var request = List.of("undo", id, hash);
        var prior = replay(pid, uid, key, request);
        if (prior != null) return repository.view(prior.response(), UndoResult.class);
        var r = repository.item("node_operation", pid, id);
        check(r, uid);
        var current = validate(r);
        if (!hash.equals(
                repository.hash(
                        List.of(
                                id,
                                conflictSnapshot(r.get("before")),
                                conflictSnapshot(r.get("after")),
                                current))))
            throw fail(409, "OPERATION_CONFLICT", "Preview is stale");
        long node = number(r.get("node_id"));
        String kind = str(r.get("kind"));
        var before = map(r.get("before"));
        if (kind.equals("update")) {
            var old = objects(before.get("nodes"), 5000).getFirst();
            repository.db.update(
                    "UPDATE node SET"
                        + " content=?,pos_x=?,pos_y=?,depth=?,order_index=?,version=version+1,updated_at=now()"
                        + " WHERE project_id=? AND id=?",
                    old.get("content"),
                    old.get("pos_x"),
                    old.get("pos_y"),
                    old.get("depth"),
                    old.get("order_index"),
                    pid,
                    node);
            history.snapshot(node, uid);
        } else if (kind.equals("create"))
            repository.db.update("DELETE FROM node WHERE project_id=? AND id=?", pid, node);
        else {
            var nodes = new ArrayList<>(objects(before.get("nodes"), 5000));
            // Legacy clients can edit depth independently of the parent relation.
            // Restore actual parents first instead of trusting the display depth.
            var remaining = new LinkedHashMap<Long, Map<String, Object>>();
            for (var n : nodes) remaining.put(number(n.get("id")), n);
            nodes.clear();
            while (!remaining.isEmpty()) {
                var ready =
                        remaining.values().stream()
                                .filter(
                                        n ->
                                                n.get("parent_id") == null
                                                        || !remaining.containsKey(
                                                                number(n.get("parent_id"))))
                                .toList();
                if (ready.isEmpty())
                    throw fail(409, "OPERATION_CONFLICT", "Saved node parents form a cycle");
                for (var n : ready) {
                    nodes.add(n);
                    remaining.remove(number(n.get("id")));
                }
            }
            for (var old : nodes) {
                var restored = new LinkedHashMap<>(old);
                restored.put("version", number(old.get("version")) + 1);
                restored.put("updated_at", Instant.now().toString());
                restoreRows("node", List.of(restored));
            }
            restoreRows("tag_node", objects(before.get("tag_nodes"), 50000));
            restoreRows("node_version", objects(before.get("versions"), 100000));
            for (var n : nodes) history.snapshot(number(n.get("id")), uid);
        }
        metrics.invalidate(pid);
        String operation = record(pid, uid, node, "undo", Map.of(), Map.of(), key, request, null);
        var result = new UndoResult(operation, id);
        repository.db.update(
                "UPDATE node_operation SET response=?::jsonb WHERE id=?",
                repository.encode(result),
                operation);
        repository.db.update("UPDATE node_operation SET undone_by=? WHERE id=?", operation, id);
        outbox.append(pid, node, "node.updated", Map.of());
        activity.append(pid, uid, "NODE_RESTORE", Map.of("operation_id", id));
        return result;
    }

    void savePatchReceipt(
            long pid, long uid, long node, String key, Object request, ApiModels.NodeView result) {
        if (key != null)
            repository.db.update(
                    "UPDATE node_operation SET request_key=?,request_hash=?,response=?::jsonb WHERE"
                        + " id=(SELECT id FROM node_operation WHERE project_id=? AND actor_id=? AND"
                        + " node_id=? AND kind='update' ORDER BY sequence DESC LIMIT 1)",
                    key,
                    repository.hash(request),
                    repository.encode(result),
                    pid,
                    uid,
                    node);
    }
}
