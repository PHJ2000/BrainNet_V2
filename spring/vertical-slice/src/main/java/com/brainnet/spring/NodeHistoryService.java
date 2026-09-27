package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.VerticalService.timestamp;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
class NodeHistoryService {
    record Version(long id, long node_id, int version_no, String content, Long author_id, OffsetDateTime created_at) {}
    private final JdbcTemplate jdbc;
    private final ProjectAccessService access;
    NodeHistoryService(JdbcTemplate jdbc, ProjectAccessService access) { this.jdbc = jdbc; this.access = access; }

    // Existing snapshots are immutable. A null actor is used for a previously unrecorded baseline.
    void snapshot(long nodeId, Long actor) {
        jdbc.update("INSERT INTO node_version(node_id,version_no,content,author_id,created_at) "
                + "SELECT id,version,content,?,updated_at FROM node WHERE id=? ON CONFLICT (node_id,version_no) DO NOTHING", actor, nodeId);
    }

    private void check(long projectId, long nodeId, long userId) {
        access.member(projectId, userId);
        if (jdbc.queryForObject("SELECT count(*) FROM node WHERE id=? AND project_id=?", Long.class, nodeId, projectId) == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NODE_NOT_FOUND", "Node not found");
        }
    }

    List<Version> list(long projectId, long nodeId, long userId, Integer before, int limit) {
        check(projectId, nodeId, userId);
        var args = new ArrayList<Object>(); args.add(nodeId);
        if (before != null) args.add(before);
        args.add(limit);
        return jdbc.query("SELECT * FROM node_version WHERE node_id=?" + (before == null ? "" : " AND version_no<?")
                + " ORDER BY version_no DESC LIMIT ?", (rs, row) -> new Version(rs.getLong("id"), rs.getLong("node_id"), rs.getInt("version_no"),
                        rs.getString("content"), (Long) rs.getObject("author_id"), timestamp(rs, "created_at")), args.toArray());
    }

    Version get(long projectId, long nodeId, int version, long userId) {
        check(projectId, nodeId, userId);
        var rows = jdbc.query("SELECT * FROM node_version WHERE node_id=? AND version_no=?",
                (rs, row) -> new Version(rs.getLong("id"), rs.getLong("node_id"), rs.getInt("version_no"), rs.getString("content"),
                        (Long) rs.getObject("author_id"), timestamp(rs, "created_at")), nodeId, version);
        if (rows.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NODE_VERSION_NOT_FOUND", "Saved version not found");
        return rows.getFirst();
    }
}
