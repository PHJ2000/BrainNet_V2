package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceInput.*;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;

@Service
class WorkspaceBackupService {
    private final ProjectAccessService access;
    private final ActivityService activity;

    static final int MAX_BYTES = 10 * 1024 * 1024;
    static final List<String> EXCLUDED =
            List.of(
                    "votes",
                    "metrics",
                    "history",
                    "accounts",
                    "credentials",
                    "memberships",
                    "operations");
    final WorkspaceRepository repository;
    final WorkspaceTaskService tasks;

    WorkspaceBackupService(
            ProjectAccessService access,
            ActivityService activity,
            WorkspaceRepository repository,
            WorkspaceTaskService tasks) {
        this.access = access;
        this.activity = activity;

        this.repository = repository;
        this.tasks = tasks;
    }

    static String rawText(Map<String, Object> b, String k, int min, int max, boolean nullable) {
        Object o = b.get(k);
        if (o == null && nullable) return null;
        if (!(o instanceof String t) || !validText(t, min, max))
            throw fail(422, "BACKUP_INVALID", "Invalid " + k);
        return t;
    }

    static String ref(Map<String, Object> b, String k, boolean nullable) {
        return rawText(b, k, 1, 80, nullable);
    }

    static void time(Object x) {
        try {
            OffsetDateTime.parse(str(x));
        } catch (Exception e) {
            throw fail(422, "BACKUP_INVALID", "Invalid timestamp");
        }
    }

    static List<Map<String, Object>> list(Map<String, Object> b, String key, int max) {
        return objects(b.getOrDefault(key, List.of()), max);
    }

    static Map<String, Map<String, Object>> indexed(
            List<Map<String, Object>> rows, boolean optional) {
        var out = new LinkedHashMap<String, Map<String, Object>>();
        for (var r : rows) {
            String id = ref(r, "ref", optional);
            if (id != null && out.put(id, r) != null)
                throw fail(422, "BACKUP_INVALID", "Duplicate reference");
        }
        return out;
    }

    static void contains(Set<String> refs, Object value, boolean nullable) {
        if (value == null && nullable) return;
        if (!(value instanceof String) || !refs.contains(value))
            throw fail(422, "BACKUP_INVALID", "Unknown reference");
    }

    Map<String, Object> graph(Map<String, Object> b) {
        return number(b.get("schema_version")) == 2 ? map(b.get("graph")) : b;
    }

    Map<String, Object> parse(byte[] raw) {
        if (raw.length > MAX_BYTES) throw fail(413, "BACKUP_TOO_LARGE", "File exceeds 10 MiB");
        try {
            var mapper =
                    tools.jackson.databind.json.JsonMapper.builder()
                            .enable(tools.jackson.core.StreamReadFeature.STRICT_DUPLICATE_DETECTION)
                            .build();
            var b = map(mapper.readValue(raw, Object.class));
            validate(b);
            return b;
        } catch (ApiExceptionHandler.ApiException e) {
            throw e;
        } catch (Exception e) {
            throw fail(422, "BACKUP_INVALID", "Invalid UTF-8 JSON");
        }
    }

    void validate(Map<String, Object> b) {
        long v = integer(b, "schema_version", 1, 2, -1);
        if (v == 2)
            fields(
                    b,
                    "schema_version",
                    "graph",
                    "tasks",
                    "discussions",
                    "proposals",
                    "bookmarks",
                    "replies",
                    "links",
                    "dependencies");
        var g = graph(b);
        fields(
                g,
                "schema_version",
                "exported_at",
                "project",
                "nodes",
                "tags",
                "node_tags",
                "depth_adjustments");
        if (integer(g, "schema_version", 1, 1, -1) != 1)
            throw fail(422, "BACKUP_VERSION", "Unsupported graph schema");
        time(g.get("exported_at"));
        var p = map(g.get("project"));
        fields(p, "name", "description");
        rawText(p, "name", 1, 120, false);
        rawText(p, "description", 0, Integer.MAX_VALUE, true);
        p.putIfAbsent("description", null);
        var nodes = list(g, "nodes", 5000);
        var tags = list(g, "tags", 5000);
        var ns = indexed(nodes, false);
        var ts = indexed(tags, false);
        int roots = 0;
        for (var n : nodes) {
            fields(
                    n,
                    "ref",
                    "parent_ref",
                    "content",
                    "state",
                    "depth",
                    "order_index",
                    "pos_x",
                    "pos_y");
            rawText(n, "content", 0, Integer.MAX_VALUE, false);
            choice(n, "state", null, "ACTIVE", "GHOST", "ARCHIVED");
            long depth = integer(n, "depth", 0, 100, -1);
            integer(n, "order_index", 0, 2147483647, -1);
            if (n.get("parent_ref") == null) {
                if (depth != 0) throw fail(422, "BACKUP_INVALID", "Root depth must be zero");
                if ("ACTIVE".equals(n.get("state"))) roots++;
            } else {
                contains(ns.keySet(), n.get("parent_ref"), false);
                if (depth != number(ns.get(n.get("parent_ref")).get("depth")) + 1)
                    throw fail(422, "BACKUP_INVALID", "Invalid parent depth or cycle");
            }
            for (String key : List.of("pos_x", "pos_y"))
                if (n.get(key) != null
                        && (!(n.get(key) instanceof Number f) || !Double.isFinite(f.doubleValue())))
                    throw fail(422, "BACKUP_INVALID", "Invalid coordinate");
        }
        if (roots > 1) throw fail(422, "BACKUP_INVALID", "Only one active root allowed");
        for (var t : tags) {
            fields(t, "ref", "name", "color");
            rawText(t, "name", 0, 80, false);
            rawText(t, "color", 0, 7, true);
            t.putIfAbsent("color", null);
        }
        var pairs = new HashSet<String>();
        for (var r : list(g, "node_tags", 50000)) {
            fields(r, "node_ref", "tag_ref");
            contains(ns.keySet(), r.get("node_ref"), false);
            contains(ts.keySet(), r.get("tag_ref"), false);
            if (!pairs.add(repository.encode(r)))
                throw fail(422, "BACKUP_INVALID", "Duplicate node tag");
        }
        var adjusted = new HashSet<String>();
        for (var a : list(g, "depth_adjustments", 5000)) {
            fields(a, "node_ref", "stored_depth", "depth");
            contains(ns.keySet(), a.get("node_ref"), false);
            integer(a, "stored_depth", Short.MIN_VALUE, Short.MAX_VALUE, Long.MIN_VALUE);
            if (!adjusted.add(str(a.get("node_ref")))
                    || integer(a, "depth", 0, 100, -1)
                            != number(ns.get(a.get("node_ref")).get("depth")))
                throw fail(422, "BACKUP_INVALID", "Invalid depth adjustment");
        }
        g.putIfAbsent("depth_adjustments", List.of());
        if (v == 1) return;
        var work = list(b, "tasks", 1000);
        var ws = indexed(work, false);
        var discussions = list(b, "discussions", 2000);
        var ds = indexed(discussions, true);
        var recurrence = new HashMap<String, Set<String>>();
        var parents = new HashSet<String>();
        for (var t : work) {
            fields(
                    t,
                    "ref",
                    "node_ref",
                    "title",
                    "body",
                    "status",
                    "priority",
                    "due_date",
                    "created_at",
                    "checklist",
                    "repeat_every_days",
                    "recurrence_parent_ref");
            contains(ns.keySet(), t.get("node_ref"), true);
            time(t.get("created_at"));
            TaskFields.parse(t).requireCompleteChecklist();
            t.putIfAbsent("node_ref", null);
            t.putIfAbsent("due_date", null);
            t.putIfAbsent("checklist", List.of());
            t.putIfAbsent("repeat_every_days", null);
            t.putIfAbsent("recurrence_parent_ref", null);
            String parent = ref(t, "recurrence_parent_ref", true);
            if (parent != null) {
                contains(ws.keySet(), parent, false);
                if (!parents.add(parent))
                    throw fail(422, "BACKUP_INVALID", "Duplicate recurrence parent");
                recurrence.put(str(t.get("ref")), Set.of(parent));
            }
        }
        acyclic(ws.keySet(), recurrence);
        for (var d : discussions) {
            fields(d, "ref", "node_ref", "body", "resolved", "created_at");
            rawText(d, "body", 1, 8000, false);
            if (!(d.get("resolved") instanceof Boolean))
                throw fail(422, "BACKUP_INVALID", "Invalid resolved value");
            contains(ns.keySet(), d.get("node_ref"), true);
            time(d.get("created_at"));
            d.putIfAbsent("ref", null);
            d.putIfAbsent("node_ref", null);
        }
        for (var r : list(b, "replies", 5000)) {
            fields(r, "discussion_ref", "body", "created_at");
            contains(ds.keySet(), r.get("discussion_ref"), false);
            rawText(r, "body", 1, 8000, false);
            time(r.get("created_at"));
        }
        pairs.clear();
        for (var l : list(b, "links", 10000)) {
            fields(l, "source_ref", "target_ref", "label");
            contains(ns.keySet(), l.get("source_ref"), false);
            contains(ns.keySet(), l.get("target_ref"), false);
            rawText(l, "label", 0, 120, true);
            l.putIfAbsent("label", "");
            var pair = new TreeSet<>(List.of(str(l.get("source_ref")), str(l.get("target_ref"))));
            if (pair.size() < 2 || !pairs.add(repository.encode(pair)))
                throw fail(422, "BACKUP_INVALID", "Duplicate or self link");
        }
        var edges = new HashMap<String, Set<String>>();
        pairs.clear();
        for (var d : list(b, "dependencies", 10000)) {
            fields(d, "task_ref", "requires_ref");
            contains(ws.keySet(), d.get("task_ref"), false);
            contains(ws.keySet(), d.get("requires_ref"), false);
            if (!pairs.add(repository.encode(d)))
                throw fail(422, "BACKUP_INVALID", "Duplicate dependency");
            edges.computeIfAbsent(str(d.get("task_ref")), k -> new HashSet<>())
                    .add(str(d.get("requires_ref")));
            if ("DONE".equals(ws.get(d.get("task_ref")).get("status"))
                    && !"DONE".equals(ws.get(d.get("requires_ref")).get("status")))
                throw fail(422, "BACKUP_INVALID", "Incomplete prerequisite");
        }
        acyclic(ws.keySet(), edges);
        if (!(b.get("bookmarks") instanceof List<?> bookmarks)
                || bookmarks.size() > 5000
                || new HashSet<>(bookmarks).size() != bookmarks.size())
            throw fail(422, "BACKUP_INVALID", "Invalid bookmarks");
        for (Object ref : bookmarks) contains(ns.keySet(), ref, false);
        for (var a : list(b, "proposals", 500)) {
            fields(
                    a,
                    "mode",
                    "instruction",
                    "sources",
                    "status",
                    "output",
                    "error_code",
                    "task_ref",
                    "created_at");
            choice(a, "mode", null, "EXPAND", "SUMMARY", "ACTION");
            rawText(a, "instruction", 0, 1000, false);
            choice(
                    a,
                    "status",
                    null,
                    "QUEUED",
                    "RUNNING",
                    "READY",
                    "FAILED",
                    "INTERRUPTED",
                    "ACCEPTED",
                    "CANCELED");
            rawText(a, "output", 0, 12000, true);
            rawText(a, "error_code", 0, 80, true);
            time(a.get("created_at"));
            contains(ws.keySet(), a.get("task_ref"), true);
            var sources = list(a, "sources", 8);
            if (sources.isEmpty()) throw fail(422, "BACKUP_INVALID", "Sources required");
            for (var src : sources) {
                fields(src, "node_ref", "content");
                contains(ns.keySet(), src.get("node_ref"), true);
                rawText(src, "content", 0, 4000, false);
                src.putIfAbsent("node_ref", null);
            }
            if ("ACCEPTED".equals(a.get("status")) && a.get("task_ref") == null)
                throw fail(422, "BACKUP_INVALID", "Accepted proposal needs task");
            if (Set.of("READY", "ACCEPTED").contains(str(a.get("status")))
                    && str(a.get("output")).isEmpty())
                throw fail(422, "BACKUP_INVALID", "Completed proposal needs output");
            for (String key : List.of("output", "error_code", "task_ref")) a.putIfAbsent(key, null);
        }
        for (String key : List.of("replies", "links", "dependencies"))
            b.putIfAbsent(key, List.of());
    }

    static void acyclic(Set<String> ids, Map<String, Set<String>> edges) {
        var graph = new HashMap<String, Set<String>>();
        for (String id : ids) graph.put(id, new HashSet<>(edges.getOrDefault(id, Set.of())));
        while (!graph.isEmpty()) {
            var ready = new HashSet<String>();
            graph.forEach(
                    (k, v) -> {
                        if (v.isEmpty()) ready.add(k);
                    });
            if (ready.isEmpty()) throw fail(422, "BACKUP_INVALID", "Cycle detected");
            ready.forEach(graph::remove);
            graph.values().forEach(v -> v.removeAll(ready));
        }
    }

    WorkspaceViews.BackupPreview preview(Map<String, Object> b) {
        var g = graph(b);
        var p = map(g.get("project"));
        var result = new LinkedHashMap<String, Object>();
        result.put("name", p.get("name"));
        result.put("description", p.get("description"));
        result.put("node_count", list(g, "nodes", 5000).size());
        result.put("tag_count", list(g, "tags", 5000).size());
        result.put("link_count", list(g, "node_tags", 50000).size());
        result.put("excluded", EXCLUDED);
        result.put("depth_adjustments", g.get("depth_adjustments"));
        var states = new LinkedHashMap<String, Object>();
        for (String state : List.of("ACTIVE", "GHOST", "ARCHIVED"))
            states.put(
                    state,
                    list(g, "nodes", 5000).stream()
                            .filter(n -> state.equals(n.get("state")))
                            .count());
        result.put("states", states);
        if (number(b.get("schema_version")) == 2) {
            result.put("schema_version", 2);
            var keys =
                    Map.of(
                            "tasks",
                            "task_count",
                            "discussions",
                            "discussion_count",
                            "proposals",
                            "proposal_count",
                            "bookmarks",
                            "bookmark_count",
                            "replies",
                            "reply_count",
                            "links",
                            "knowledge_link_count",
                            "dependencies",
                            "dependency_count");
            keys.forEach((k, v) -> result.put(v, ((List<?>) b.getOrDefault(k, List.of())).size()));
        }
        return repository.view(result, WorkspaceViews.BackupPreview.class);
    }

    List<Map<String, Object>> bounded(String sql, int max, Object... args) {
        var rows = repository.rows(sql + " LIMIT " + (max + 1), args);
        if (rows.size() > max) throw fail(422, "WORKSPACE_EXPORT_LIMIT", "Export limit exceeded");
        return rows;
    }

    List<Map<String, Object>> ordered(List<Map<String, Object>> nodes) {
        var remaining = new ArrayList<>(nodes);
        var ordered = new ArrayList<Map<String, Object>>();
        var children = new HashMap<String, List<Map<String, Object>>>();
        for (var n : nodes)
            children.computeIfAbsent(str(n.get("parent_id")), k -> new ArrayList<>()).add(n);
        for (var c : children.values())
            c.sort(
                    Comparator.<Map<String, Object>>comparingLong(n -> number(n.get("order_index")))
                            .thenComparingLong(n -> number(n.get("id"))));
        var stack = new ArrayDeque<Map<String, Object>>();
        var roots = children.getOrDefault("", List.of());
        for (int i = roots.size() - 1; i >= 0; i--) stack.push(roots.get(i));
        while (!stack.isEmpty()) {
            var n = stack.pop();
            ordered.add(n);
            var list = children.getOrDefault(str(n.get("id")), List.of());
            for (int i = list.size() - 1; i >= 0; i--) stack.push(list.get(i));
            if (ordered.size() > nodes.size()) throw fail(422, "INVALID_GRAPH", "Graph cycle");
        }
        if (ordered.size() != remaining.size())
            throw fail(422, "INVALID_GRAPH", "Graph has missing parent or cycle");
        return ordered;
    }

    @Transactional(isolation = Isolation.REPEATABLE_READ, readOnly = true)
    public Map<String, Object> export(long pid, long uid, boolean workspace) {
        access.member(pid, uid);
        var project = repository.one("SELECT name,description FROM project WHERE id=?", pid);
        var nodes =
                ordered(
                        bounded(
                                "SELECT id,parent_id,content,state::text"
                                        + " state,depth,order_index,pos_x,pos_y FROM node WHERE"
                                        + " project_id=? ORDER BY id",
                                5000,
                                pid));
        var tags =
                bounded("SELECT id,name,color FROM tag WHERE project_id=? ORDER BY id", 5000, pid);
        var links =
                bounded(
                        "SELECT tn.node_id,tn.tag_id FROM tag_node tn JOIN node n ON"
                                + " n.id=tn.node_id WHERE n.project_id=? ORDER BY node_id,tag_id",
                        50000,
                        pid);
        var refs = new HashMap<Long, String>();
        var depths = new HashMap<Long, Long>();
        var graphNodes = new ArrayList<Map<String, Object>>();
        var adjustments = new ArrayList<Map<String, Object>>();
        for (var n : nodes) {
            long id = number(n.get("id"));
            refs.put(id, "n" + (refs.size() + 1));
            long depth =
                    n.get("parent_id") == null ? 0 : depths.get(number(n.get("parent_id"))) + 1;
            depths.put(id, depth);
            var row = pick(n, "content", "state", "order_index", "pos_x", "pos_y");
            row.put("ref", refs.get(id));
            row.put(
                    "parent_ref",
                    n.get("parent_id") == null ? null : refs.get(number(n.get("parent_id"))));
            row.put("depth", depth);
            graphNodes.add(row);
            if (depth != number(n.get("depth")))
                adjustments.add(
                        Map.of(
                                "node_ref",
                                refs.get(id),
                                "stored_depth",
                                n.get("depth"),
                                "depth",
                                depth));
        }
        var tagRefs = new HashMap<Long, String>();
        var graphTags = new ArrayList<Map<String, Object>>();
        for (var tag : tags) {
            long id = number(tag.get("id"));
            String ref = "t" + (tagRefs.size() + 1);
            tagRefs.put(id, ref);
            var row = pick(tag, "name", "color");
            row.put("ref", ref);
            graphTags.add(row);
        }
        var graphLinks = new ArrayList<Map<String, Object>>();
        for (var link : links) {
            String tag = tagRefs.get(number(link.get("tag_id")));
            if (tag == null) throw fail(422, "INVALID_GRAPH", "Cross-project tag");
            graphLinks.add(
                    Map.of("node_ref", refs.get(number(link.get("node_id"))), "tag_ref", tag));
        }
        graphLinks.sort(Comparator.comparing(r -> str(r.get("node_ref")) + "/" + r.get("tag_ref")));
        var graph = new LinkedHashMap<String, Object>();
        graph.put("schema_version", 1);
        graph.put("exported_at", Instant.now().toString());
        graph.put("project", project);
        graph.put("nodes", graphNodes);
        graph.put("tags", graphTags);
        graph.put("node_tags", graphLinks);
        graph.put("depth_adjustments", adjustments);
        if (!workspace) {
            validate(graph);
            size(graph);
            return graph;
        }
        var result = new LinkedHashMap<String, Object>();
        result.put("schema_version", 2);
        result.put("graph", graph);
        var work =
                bounded(
                        "SELECT * FROM work_item WHERE project_id=? ORDER BY created_at,id",
                        1000,
                        pid);
        var workRefs = new HashMap<String, String>();
        for (var t : work) workRefs.put(str(t.get("id")), "w" + (workRefs.size() + 1));
        var savedTasks = new ArrayList<Map<String, Object>>();
        for (var t : work) {
            var row =
                    pick(
                            t,
                            "title",
                            "body",
                            "status",
                            "priority",
                            "due_date",
                            "created_at",
                            "checklist",
                            "repeat_every_days");
            row.put("ref", workRefs.get(str(t.get("id"))));
            row.put(
                    "node_ref",
                    t.get("node_id") == null ? null : refs.get(number(t.get("node_id"))));
            row.put("recurrence_parent_ref", workRefs.get(str(t.get("recurrence_parent_id"))));
            savedTasks.add(row);
        }
        result.put("tasks", savedTasks);
        var threads =
                bounded(
                        "SELECT * FROM discussion WHERE project_id=? ORDER BY created_at,id",
                        2000,
                        pid);
        var threadRefs = new HashMap<String, String>();
        var savedThreads = new ArrayList<Map<String, Object>>();
        for (var d : threads) {
            String ref = "d" + (threadRefs.size() + 1);
            threadRefs.put(str(d.get("id")), ref);
            var row = pick(d, "body", "resolved", "created_at");
            row.put("ref", ref);
            row.put(
                    "node_ref",
                    d.get("node_id") == null ? null : refs.get(number(d.get("node_id"))));
            savedThreads.add(row);
        }
        result.put("discussions", savedThreads);
        var savedProposals = new ArrayList<Map<String, Object>>();
        for (var p :
                bounded(
                        "SELECT * FROM ai_proposal WHERE project_id=? ORDER BY created_at,id",
                        500,
                        pid)) {
            var row =
                    pick(p, "mode", "instruction", "status", "output", "error_code", "created_at");
            row.put("task_ref", workRefs.get(str(p.get("task_id"))));
            var sources = new ArrayList<Map<String, Object>>();
            for (var source : objects(p.get("sources"), 8)) {
                var src = pick(source, "content");
                src.put("node_ref", refs.get(number(source.get("id"))));
                sources.add(src);
            }
            row.put("sources", sources);
            savedProposals.add(row);
        }
        result.put("proposals", savedProposals);
        result.put(
                "bookmarks",
                repository
                        .rows(
                                "SELECT b.node_id FROM node_bookmark b JOIN node n ON"
                                    + " n.id=b.node_id WHERE n.project_id=? AND b.user_id=? ORDER"
                                    + " BY b.node_id",
                                pid,
                                uid)
                        .stream()
                        .map(r -> refs.get(number(r.get("node_id"))))
                        .toList());
        var replies = new ArrayList<Map<String, Object>>();
        for (var r :
                bounded(
                        "SELECT * FROM discussion_reply WHERE project_id=? ORDER BY created_at,id",
                        5000,
                        pid)) {
            var saved = pick(r, "body", "created_at");
            saved.put("discussion_ref", threadRefs.get(str(r.get("discussion_id"))));
            replies.add(saved);
        }
        result.put("replies", replies);
        result.put(
                "links",
                bounded(
                                "SELECT k.* FROM knowledge_link k JOIN node n ON n.id=k.source_id"
                                        + " WHERE n.project_id=? ORDER BY source_id,target_id",
                                10000,
                                pid)
                        .stream()
                        .map(
                                r ->
                                        Map.of(
                                                "source_ref",
                                                refs.get(number(r.get("source_id"))),
                                                "target_ref",
                                                refs.get(number(r.get("target_id"))),
                                                "label",
                                                r.get("label")))
                        .toList());
        result.put(
                "dependencies",
                bounded(
                                "SELECT d.* FROM task_dependency d JOIN work_item t ON"
                                        + " t.id=d.task_id WHERE t.project_id=? ORDER BY"
                                        + " task_id,requires_id",
                                10000,
                                pid)
                        .stream()
                        .map(
                                r ->
                                        Map.of(
                                                "task_ref",
                                                workRefs.get(str(r.get("task_id"))),
                                                "requires_ref",
                                                workRefs.get(str(r.get("requires_id")))))
                        .toList());
        validate(result);
        size(result);
        return result;
    }

    void size(Object value) {
        if (repository.encode(value).getBytes(StandardCharsets.UTF_8).length > MAX_BYTES)
            throw fail(413, "BACKUP_TOO_LARGE", "Export exceeds 10 MiB");
    }

    String fingerprint(Map<String, Object> b) {
        var portable = map(repository.decode(repository.encode(b)));
        if (number(b.get("schema_version")) == 2) {
            for (String key : List.of("replies", "links", "dependencies"))
                if (((List<?>) portable.get(key)).isEmpty()) portable.remove(key);
            for (var d : list(portable, "discussions", 2000))
                if (d.get("ref") == null) d.remove("ref");
            for (var t : list(portable, "tasks", 1000))
                for (String key :
                        List.of("checklist", "repeat_every_days", "recurrence_parent_ref"))
                    if (t.get(key) == null || (t.get(key) instanceof List<?> l && l.isEmpty()))
                        t.remove(key);
        }
        return repository.hash(portable);
    }

    @Transactional
    public WorkspaceViews.ImportedProject restore(long uid, String key, Map<String, Object> b) {
        validate(b);
        if (key == null || key.isBlank() || key.length() > 128)
            throw fail(422, "IDEMPOTENCY_KEY_INVALID", "Invalid request key");
        repository.db.queryForObject(
                "SELECT pg_advisory_xact_lock(hashtextextended(?,0))",
                Object.class,
                "project-import:" + uid + ":" + key);
        String hash = fingerprint(b);
        var prior =
                repository.one(
                        "SELECT * FROM project_import WHERE actor_id=? AND request_key=?",
                        uid,
                        key);
        if (prior != null) {
            if (!hash.equals(prior.get("request_hash")))
                throw fail(409, "IDEMPOTENCY_KEY_REUSED", "Key belongs to a different backup");
            var p =
                    repository.one(
                            "SELECT id project_id,name FROM project WHERE id=? AND owner_id=? AND"
                                    + " is_deleted=false",
                            prior.get("project_id"),
                            uid);
            if (p == null)
                throw fail(410, "IMPORT_RESULT_GONE", "Imported project is no longer available");
            return repository.view(p, WorkspaceViews.ImportedProject.class);
        }
        var graph = graph(b);
        var project = map(graph.get("project"));
        long pid =
                repository.db.queryForObject(
                        "INSERT INTO"
                            + " project(owner_id,name,description,is_deleted,created_at,updated_at)"
                            + " VALUES(?,?,?,false,now(),now()) RETURNING id",
                        Long.class,
                        uid,
                        project.get("name"),
                        project.get("description"));
        repository.db.update(
                "INSERT INTO project_user_role(project_id,user_id,role,invited_at,accepted_at)"
                        + " VALUES(?,?,'OWNER',now(),now())",
                pid,
                uid);
        var nodes = new ArrayList<>(list(graph, "nodes", 5000));
        nodes.sort(Comparator.comparingLong(n -> number(n.get("depth"))));
        var nodeRefs = new HashMap<String, Long>();
        for (var n : nodes) {
            long id =
                    repository.db.queryForObject(
                            "INSERT INTO"
                                + " node(project_id,author_id,parent_id,content,state,depth,order_index,pos_x,pos_y,version,created_at,updated_at)"
                                + " VALUES(?,?,?,?,?::node_state_t,?,?,?,?,0,now(),now()) RETURNING"
                                + " id",
                            Long.class,
                            pid,
                            uid,
                            nodeRefs.get(n.get("parent_ref")),
                            n.get("content"),
                            n.get("state"),
                            n.get("depth"),
                            n.get("order_index"),
                            n.get("pos_x"),
                            n.get("pos_y"));
            nodeRefs.put(str(n.get("ref")), id);
            repository.db.update(
                    "INSERT INTO node_version(node_id,version_no,content,author_id,created_at)"
                            + " VALUES(?,0,?,?,now())",
                    id,
                    n.get("content"),
                    uid);
        }
        var tagRefs = new HashMap<String, Long>();
        for (var t : list(graph, "tags", 5000)) {
            long id =
                    repository.db.queryForObject(
                            "INSERT INTO tag(project_id,name,color) VALUES(?,?,?) RETURNING id",
                            Long.class,
                            pid,
                            t.get("name"),
                            t.get("color"));
            tagRefs.put(str(t.get("ref")), id);
        }
        for (var r : list(graph, "node_tags", 50000))
            repository.db.update(
                    "INSERT INTO tag_node(node_id,tag_id) VALUES(?,?)",
                    nodeRefs.get(r.get("node_ref")),
                    tagRefs.get(r.get("tag_ref")));
        if (number(b.get("schema_version")) == 2) restoreWorkspace(pid, uid, b, nodeRefs);
        repository.db.update(
                "INSERT INTO"
                        + " project_import(actor_id,request_key,request_hash,project_id,created_at)"
                        + " VALUES(?,?,?,?,now())",
                uid,
                key,
                hash,
                pid);
        activity.recordWorkspace(pid, uid, "project.imported", pid);
        return new WorkspaceViews.ImportedProject(pid, str(project.get("name")));
    }

    void restoreWorkspace(long pid, long uid, Map<String, Object> b, Map<String, Long> nodes) {
        var refs = new HashMap<String, String>();
        for (var t : list(b, "tasks", 1000)) {
            String id = UUID.randomUUID().toString();
            refs.put(str(t.get("ref")), id);
            var input = new LinkedHashMap<>(t);
            input.put("node_id", nodes.get(t.get("node_ref")));
            var n = TaskFields.parse(input).withText(str(t.get("title")), str(t.get("body")));
            tasks.insert(pid, uid, id, n, "imported", null);
            repository.db.update(
                    "UPDATE work_item SET created_at=?::timestamptz WHERE id=?",
                    t.get("created_at"),
                    id);
        }
        for (var t : list(b, "tasks", 1000))
            if (t.get("recurrence_parent_ref") != null)
                repository.db.update(
                        "UPDATE work_item SET recurrence_parent_id=? WHERE id=?",
                        refs.get(t.get("recurrence_parent_ref")),
                        refs.get(t.get("ref")));
        var threads = new HashMap<String, String>();
        for (var d : list(b, "discussions", 2000)) {
            String id = UUID.randomUUID().toString();
            if (d.get("ref") != null) threads.put(str(d.get("ref")), id);
            repository.db.update(
                    "INSERT INTO"
                        + " discussion(id,project_id,node_id,author_id,body,resolved,version,request_hash,created_at,updated_at)"
                        + " VALUES(?,?,?,?,?,?,0,'imported',?::timestamptz,now())",
                    id,
                    pid,
                    nodes.get(d.get("node_ref")),
                    uid,
                    d.get("body"),
                    d.get("resolved"),
                    d.get("created_at"));
        }
        for (var r : list(b, "replies", 5000))
            repository.db.update(
                    "INSERT INTO"
                        + " discussion_reply(id,project_id,discussion_id,author_id,body,mentions,request_hash,created_at)"
                        + " VALUES(?,?,?,?,?,'[]','imported',?::timestamptz)",
                    UUID.randomUUID().toString(),
                    pid,
                    threads.get(r.get("discussion_ref")),
                    uid,
                    r.get("body"),
                    r.get("created_at"));
        for (var l : list(b, "links", 10000))
            repository.db.update(
                    "INSERT INTO knowledge_link(source_id,target_id,label,creator_id,created_at)"
                            + " VALUES(?,?,?,?,now())",
                    nodes.get(l.get("source_ref")),
                    nodes.get(l.get("target_ref")),
                    l.get("label"),
                    uid);
        for (var d : list(b, "dependencies", 10000))
            repository.db.update(
                    "INSERT INTO task_dependency(task_id,requires_id) VALUES(?,?)",
                    refs.get(d.get("task_ref")),
                    refs.get(d.get("requires_ref")));
        for (var a : list(b, "proposals", 500)) {
            var sources = new ArrayList<Map<String, Object>>();
            for (var src : list(a, "sources", 8))
                sources.add(
                        Map.of(
                                "id",
                                nodes.getOrDefault(src.get("node_ref"), 0L),
                                "version",
                                0,
                                "content",
                                src.get("content")));
            boolean interrupted = Set.of("QUEUED", "RUNNING").contains(str(a.get("status")));
            repository.db.update(
                    "INSERT INTO"
                        + " ai_proposal(id,project_id,actor_id,mode,instruction,sources,status,output,error_code,task_id,request_hash,created_at,updated_at)"
                        + " VALUES(?,?,?,?,?,?::jsonb,?,?,?,?,'imported',?::timestamptz,now())",
                    UUID.randomUUID().toString(),
                    pid,
                    uid,
                    a.get("mode"),
                    a.get("instruction"),
                    repository.encode(sources),
                    interrupted ? "INTERRUPTED" : a.get("status"),
                    a.get("output"),
                    interrupted ? "AI_REQUEST_INTERRUPTED" : a.get("error_code"),
                    refs.get(a.get("task_ref")),
                    a.get("created_at"));
        }
        for (Object ref : (List<?>) b.get("bookmarks"))
            repository.db.update(
                    "INSERT INTO node_bookmark(user_id,node_id,created_at) VALUES(?,?,now())",
                    uid,
                    nodes.get(ref));
    }

    String encode(Object backup) {
        return repository.encode(backup);
    }

    List<Map<String, Object>> orderedNodes(long projectId) {
        return ordered(
                repository.rows(
                        "SELECT id,parent_id,order_index FROM node WHERE project_id=? ORDER BY id",
                        projectId));
    }
}
