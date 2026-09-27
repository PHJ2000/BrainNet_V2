package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class TagService {
    record Create(@NotNull @Size(max = 80) String name, @Size(max = 7) String color) {}
    record Patch(@Size(max = 80) String name, @Size(max = 7) String color) {}
    record View(long id, long project_id, String name, String color, long node_count) {}
    private static final String SELECT = "SELECT t.*,(SELECT count(*) FROM tag_node WHERE tag_id=t.id) node_count "
            + "FROM tag t JOIN project p ON p.id=t.project_id AND p.is_deleted=false ";
    private final JdbcTemplate jdbc;
    private final VerticalService nodes;
    private final ProjectService projects;
    private final ActivityService activity;
    TagService(JdbcTemplate jdbc, VerticalService nodes, ProjectService projects, ActivityService activity) {
        this.jdbc = jdbc; this.nodes = nodes; this.projects = projects; this.activity = activity;
    }

    private View view(ResultSet rs, int row) throws SQLException {
        return new View(rs.getLong("id"), rs.getLong("project_id"), rs.getString("name"), rs.getString("color"), rs.getLong("node_count"));
    }

    List<View> list(long projectId, long userId) {
        nodes.requireMember(projectId, userId);
        return jdbc.query(SELECT + "WHERE t.project_id=? ORDER BY t.id", this::view, projectId);
    }

    View get(long projectId, long tagId, long userId) {
        nodes.requireMember(projectId, userId);
        var tags = jdbc.query(SELECT + "WHERE t.project_id=? AND t.id=?", this::view, projectId, tagId);
        if (tags.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Tag not found");
        return tags.getFirst();
    }

    @Transactional
    public View create(long projectId, long userId, Create body) {
        nodes.requireMember(projectId, userId);
        long id = jdbc.queryForObject("INSERT INTO tag(project_id,name,color) VALUES (?,?,?) RETURNING id",
                Long.class, projectId, body.name(), body.color());
        activity.append(projectId, userId, "TAG_CREATE", Map.of("tag_id", id));
        return get(projectId, id, userId);
    }

    @Transactional
    public View update(long projectId, long tagId, long userId, Patch body) {
        get(projectId, tagId, userId);
        jdbc.update("UPDATE tag SET name=coalesce(?,name),color=coalesce(?,color) WHERE id=?", body.name(), body.color(), tagId);
        activity.append(projectId, userId, "TAG_UPDATE", Map.of("tag_id", tagId));
        return get(projectId, tagId, userId);
    }

    @Transactional
    public void delete(long projectId, long tagId, long userId) {
        projects.lockActive(projectId);
        get(projectId, tagId, userId);
        if (jdbc.queryForObject("SELECT count(*) FROM tag_summary s WHERE s.tag_id=? AND "
                + "(EXISTS (SELECT 1 FROM vote v WHERE v.tag_summary_id=s.id) "
                + "OR EXISTS (SELECT 1 FROM project_history h WHERE h.tag_summary_id=s.id))", Long.class, tagId) > 0) {
            throw new ApiException(HttpStatus.CONFLICT, "TAG_IN_USE", "Tag is referenced by votes or decision history");
        }
        jdbc.update("DELETE FROM tag WHERE id=?", tagId);
        activity.append(projectId, userId, "TAG_DELETE", Map.of("tag_id", tagId));
    }

    @Transactional
    public Map<String, Object> attach(long projectId, long tagId, long nodeId, long userId, boolean attach) {
        get(projectId, tagId, userId);
        List<Long> ids = nodes.lockSubtree(projectId, nodeId);
        boolean exists = jdbc.queryForObject("SELECT count(*) FROM tag_node WHERE tag_id=? AND node_id=?", Long.class, tagId, nodeId) > 0;
        if (attach && exists) throw new ApiException(HttpStatus.CONFLICT, "CONFLICT", "Already attached");
        if (!attach && !exists) throw new ApiException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "Node not tagged");
        for (long id : ids) {
            if (attach) jdbc.update("INSERT INTO tag_node(tag_id,node_id) VALUES (?,?) ON CONFLICT DO NOTHING", tagId, id);
            else jdbc.update("DELETE FROM tag_node WHERE tag_id=? AND node_id=?", tagId, id);
        }
        activity.append(projectId, userId, attach ? "TAG_APPLY" : "TAG_REMOVE",
                Map.of("tag_id", tagId, "node_id", nodeId, "subtree_size", ids.size()));
        return Map.of("tag_id", tagId, "node_id", nodeId, "status", attach ? "attached" : "detached");
    }
}
