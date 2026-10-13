package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceInput.*;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import tools.jackson.databind.ObjectMapper;

import java.sql.*;
import java.time.*;
import java.util.*;

/** Workspace persistence and JSON row mapping. SQL identifiers are internal constants. */
@Service
class WorkspaceRepository {
    final JdbcTemplate db;
    final ObjectMapper json;

    WorkspaceRepository(JdbcTemplate db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    String encode(Object o) {
        return json.writeValueAsString(o);
    }

    @SuppressWarnings("unchecked")
    <T> T decode(String s) {
        return (T) json.readValue(s, Object.class);
    }

    String hash(Object value) {
        return WorkspaceRequestHash.digest(encode(canonical(value)));
    }

    WorkspaceRequestHash requestHash(Object value) {
        Object document = json.convertValue(value, Object.class);
        return new WorkspaceRequestHash(
                hash(document), WorkspaceRequestHash.legacy(json, document));
    }

    WorkspaceRequestHash taskRequestHash(String id, TaskFields task) {
        var fields = task.asMap();
        var legacy = new LinkedHashMap<>(fields);
        legacy.put("id", id);
        // V3 task_execution.task_digest omits empty execution fields for pre-checklist retries.
        if (((List<?>) legacy.get("checklist")).isEmpty()) legacy.remove("checklist");
        if (legacy.get("repeat_every_days") == null) legacy.remove("repeat_every_days");
        return new WorkspaceRequestHash(hash(fields), WorkspaceRequestHash.legacy(json, legacy));
    }

    Object canonical(Object o) {
        if (o instanceof Map<?, ?> m) {
            var out = new TreeMap<String, Object>();
            m.forEach((k, v) -> out.put(k.toString(), canonical(v)));
            return out;
        }
        if (o instanceof List<?> l) return l.stream().map(this::canonical).toList();
        return o;
    }

    List<Map<String, Object>> rows(String sql, Object... args) {
        return db.query(
                sql,
                (rs, n) -> {
                    var row = new LinkedHashMap<String, Object>();
                    var meta = rs.getMetaData();
                    for (int i = 1; i <= meta.getColumnCount(); i++) {
                        Object v = rs.getObject(i);
                        String type = meta.getColumnTypeName(i);
                        if (v != null && (type.equals("jsonb") || type.equals("json")))
                            v = decode(v.toString());
                        else if (v instanceof Timestamp t) v = t.toInstant().toString();
                        else if (v instanceof java.sql.Date d) v = d.toLocalDate().toString();
                        row.put(meta.getColumnLabel(i), v);
                    }
                    return row;
                },
                args);
    }

    Map<String, Object> one(String sql, Object... args) {
        var r = rows(sql, args);
        return r.isEmpty() ? null : r.getFirst();
    }

    Map<String, Object> item(String table, long pid, String id) {
        var r = one("SELECT * FROM " + table + " WHERE project_id=? AND id=?", pid, id);
        if (r == null) throw fail(404, "NOT_FOUND", "Item not found");
        return r;
    }

    void node(long pid, Long id) {
        if (id != null && one("SELECT id FROM node WHERE project_id=? AND id=?", pid, id) == null)
            throw fail(404, "NODE_NOT_FOUND", "Node not found");
    }

    void version(Map<String, Object> row, Object expected) {
        if (expected == null || number(row.get("version")) != number(expected))
            throw fail(409, "VERSION_CONFLICT", "Item changed; reload before saving");
    }

    Map<String, Object> replay(
            String table, String id, long pid, long uid, String actor, WorkspaceRequestHash hash) {
        var r = one("SELECT * FROM " + table + " WHERE id=?", id);
        if (r != null
                && (number(r.get("project_id")) != pid
                        || r.get(actor) == null
                        || number(r.get(actor)) != uid
                        || !hash.matches(r.get("request_hash"))))
            throw fail(409, "REQUEST_ID_REUSED", "Request ID belongs to another command");
        return r;
    }

    <T, C> WorkspaceViews.Page<T, C> list(
            String table,
            long pid,
            String before,
            int limit,
            String extra,
            List<Object> args,
            Class<T> type,
            java.util.function.Function<T, C> cursor) {
        String sql = "SELECT * FROM " + table + " WHERE project_id=?";
        var params = new ArrayList<Object>();
        params.add(pid);
        sql += extra;
        params.addAll(args);
        if (before != null && !before.isEmpty()) {
            var c = item(table, pid, before);
            sql += " AND (created_at,id)<(?::timestamptz,?)";
            params.add(c.get("created_at"));
            params.add(before);
        }
        sql += " ORDER BY created_at DESC,id DESC LIMIT ?";
        params.add(limit + 1);
        return page(rows(sql, params.toArray()), limit, type, cursor);
    }

    String like(String q) {
        return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%";
    }

    <T> T view(Object row, Class<T> type) {
        return row == null ? null : json.convertValue(row, type);
    }

    <T, C> WorkspaceViews.Page<T, C> page(
            List<Map<String, Object>> rows,
            int limit,
            Class<T> type,
            java.util.function.Function<T, C> cursor) {
        var items = rows.stream().limit(limit).map(row -> view(row, type)).toList();
        return new WorkspaceViews.Page<>(
                items, rows.size() > limit ? cursor.apply(items.getLast()) : null);
    }
}
