package com.brainnet.spring;

import static com.brainnet.spring.ApiModels.*;
import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.VerticalService.timestamp;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class ProjectService {
    record Create(@NotNull @Size(max = 120) String name, String description) {}
    record Patch(@Size(max = 120) String name, String description) {}
    private final JdbcTemplate jdbc;
    ProjectService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    private ProjectView view(ResultSet rs, int row) throws SQLException {
        return new ProjectView(rs.getLong("id"), rs.getString("name"), rs.getString("description"),
                rs.getLong("owner_id"), timestamp(rs, "created_at"), timestamp(rs, "updated_at"),
                rs.getBoolean("is_deleted"), null, null, null);
    }

    ProjectView requireOwner(long projectId, long userId) {
        var projects = jdbc.query("SELECT * FROM project WHERE id=? AND is_deleted=false", this::view, projectId);
        if (projects.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Project not found");
        if (jdbc.queryForObject("SELECT count(*) FROM project_user_role WHERE project_id=? AND user_id=? AND role='OWNER'",
                Long.class, projectId, userId) == 0) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "Owner permission required");
        }
        return projects.getFirst();
    }

    List<ProjectView> list(long userId, boolean owned) {
        return jdbc.query("SELECT p.* FROM project p JOIN project_user_role m ON m.project_id=p.id "
                + "WHERE m.user_id=?" + (owned ? " AND p.owner_id=m.user_id" : "") + " ORDER BY p.id", this::view, userId);
    }

    @Transactional
    public ProjectView create(Create body, long userId) {
        long id = jdbc.queryForObject("INSERT INTO project(owner_id,name,description,is_deleted,created_at,updated_at) "
                + "VALUES (?,?,?,false,now(),now()) RETURNING id", Long.class, userId, body.name(), body.description());
        jdbc.update("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES (?,?,'OWNER',now())", id, userId);
        jdbc.update("INSERT INTO node(project_id,author_id,content,state,depth,order_index,pos_x,pos_y,created_at,updated_at,version) "
                + "VALUES (?,?,'주제를 입력하세요','ACTIVE',0,0,800,400,now(),now(),0)", id, userId);
        return jdbc.queryForObject("SELECT * FROM project WHERE id=?", this::view, id);
    }

    @Transactional
    public ProjectView update(long projectId, long userId, Patch body) {
        requireOwner(projectId, userId);
        if (body.name() != null || body.description() != null) {
            jdbc.update("UPDATE project SET name=coalesce(?,name),description=coalesce(?,description),updated_at=now() WHERE id=?",
                    body.name(), body.description(), projectId);
        }
        return jdbc.queryForObject("SELECT * FROM project WHERE id=?", this::view, projectId);
    }

    @Transactional
    public void delete(long projectId, long userId) {
        requireOwner(projectId, userId);
        jdbc.update("UPDATE project SET is_deleted=true,updated_at=now() WHERE id=?", projectId);
    }

    Map<String, Object> summary(long projectId, long userId) {
        var project = requireOwner(projectId, userId);
        var tags = jdbc.queryForList("SELECT t.id AS tag_id,t.name AS tag_name,count(n.id) AS node_count FROM tag t "
                + "LEFT JOIN tag_node tn ON tn.tag_id=t.id LEFT JOIN node n ON n.id=tn.node_id "
                + "WHERE t.project_id=? GROUP BY t.id ORDER BY count(n.id) DESC,t.id", projectId);
        return Map.of("project_id", projectId, "project_name", project.name(), "tag_summaries", tags,
                "total_nodes", jdbc.queryForObject("SELECT count(*) FROM node WHERE project_id=?", Long.class, projectId),
                "total_tags", tags.size());
    }
}
