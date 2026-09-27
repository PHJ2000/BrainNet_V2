package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.VerticalService.timestamp;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class NodeMetricsService {
    record Metrics(long node_id, int subtree_size, double density_score, OffsetDateTime updated_at) {}
    private final JdbcTemplate jdbc;
    private final ProjectAccessService access;
    NodeMetricsService(JdbcTemplate jdbc, ProjectAccessService access) { this.jdbc = jdbc; this.access = access; }

    // Called in the same transaction as any node mutation; GET recomputes invalidated rows.
    void invalidate(long projectId) {
        jdbc.update("DELETE FROM node_metrics WHERE node_id IN (SELECT id FROM node WHERE project_id=?)", projectId);
    }

    @Transactional
    public List<Metrics> refresh(long projectId, Long nodeId, long userId) {
        // Exclusive project lock prevents a node write from racing the snapshot and cache insertion.
        if (jdbc.queryForList("SELECT id FROM project WHERE id=? AND is_deleted=false FOR UPDATE", Long.class, projectId).isEmpty()) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Project not found");
        }
        access.member(projectId, userId);
        if (nodeId != null && jdbc.queryForObject("SELECT count(*) FROM node WHERE id=? AND project_id=?", Long.class, nodeId, projectId) == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NODE_NOT_FOUND", "Node not found");
        }
        // UNION terminates even for old malformed cycles. Size includes the node itself;
        // density is ACTIVE nodes / all nodes in the subtree, independent of layout coordinates.
        String rootFilter = nodeId == null ? "" : " AND id=?";
        Object[] args = nodeId == null ? new Object[]{projectId, projectId} : new Object[]{projectId, nodeId, projectId};
        return jdbc.query("WITH RECURSIVE tree(root_id,node_id,state) AS ("
                + "SELECT id,id,state FROM node WHERE project_id=?" + rootFilter
                + " UNION SELECT t.root_id,n.id,n.state FROM tree t JOIN node n ON n.parent_id=t.node_id WHERE n.project_id=?),"
                + "counts AS (SELECT root_id,count(*)::integer AS size,count(*) FILTER (WHERE state='ACTIVE')::double precision/count(*) AS density "
                + "FROM tree GROUP BY root_id), saved AS ("
                + "INSERT INTO node_metrics(node_id,subtree_size,density_score,updated_at) SELECT root_id,size,density,clock_timestamp() FROM counts "
                + "ON CONFLICT (node_id) DO UPDATE SET subtree_size=excluded.subtree_size,density_score=excluded.density_score,updated_at=excluded.updated_at "
                + "RETURNING *) SELECT * FROM saved ORDER BY node_id",
                (rs, row) -> new Metrics(rs.getLong("node_id"), rs.getInt("subtree_size"), rs.getDouble("density_score"), timestamp(rs, "updated_at")), args);
    }
}
