package com.brainnet.vertical;

import static com.brainnet.vertical.ApiExceptionHandler.ApiException;
import static com.brainnet.vertical.ApiModels.*;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class VerticalService {
    private final JdbcTemplate jdbc;
    private final String schema;

    VerticalService(JdbcTemplate jdbc, @Value("${DB_SCHEMA:j}") String schema) {
        this.jdbc = jdbc;
        this.schema = schema;
    }

    private NodeView mapNode(ResultSet rs, int ignored) throws SQLException {
        return new NodeView(rs.getLong("id"), rs.getLong("project_id"), (Long) rs.getObject("author_id"),
                rs.getString("content"), rs.getString("state"), (Double) rs.getObject("pos_x"),
                (Double) rs.getObject("pos_y"), rs.getInt("depth"), rs.getInt("order_index"),
                (Long) rs.getObject("parent_id"), rs.getInt("version"));
    }

    @Transactional
    ProjectView createProject(ProjectCreate body, long userId, boolean fault) {
        Long id = jdbc.queryForObject("INSERT INTO " + schema + ".project(owner_id,name,description) VALUES (?,?,?) RETURNING id", Long.class, userId, body.name(), body.description());
        jdbc.update("INSERT INTO " + schema + ".project_user_role(project_id,user_id,role) VALUES (?,?,'OWNER')", id, userId);
        if (fault) jdbc.queryForObject("SELECT 1/0", Integer.class);
        jdbc.update("INSERT INTO " + schema + ".node(project_id,author_id,content,state,depth,order_index,pos_x,pos_y) VALUES (?,?,'주제를 입력하세요','ACTIVE',0,0,800,400)", id, userId);
        return new ProjectView(id, userId, body.name(), body.description());
    }

    @Transactional
    NodeView createNode(long projectId, NodeCreate body, long userId) {
        try {
            return jdbc.queryForObject("INSERT INTO " + schema + ".node(project_id,parent_id,author_id,content,state,depth,order_index,pos_x,pos_y) VALUES (?,?,?,?, 'ACTIVE',?,?,?,?) RETURNING *",
                    this::mapNode, projectId, body.parent_id() == null || body.parent_id() == 0 ? null : body.parent_id(), userId,
                    body.content(), body.depthValue(), body.orderValue(), body.posXValue(), body.posYValue());
        } catch (DuplicateKeyException ex) {
            throw new ApiException(HttpStatus.CONFLICT, "ROOT_CONFLICT", "Root node already exists for this project");
        }
    }

    NodeView getNode(long projectId, long nodeId) {
        List<NodeView> rows = jdbc.query("SELECT * FROM " + schema + ".node WHERE id=? AND project_id=?", this::mapNode, nodeId, projectId);
        if (rows.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NODE_NOT_FOUND", "Node not found");
        return rows.getFirst();
    }

    @Transactional
    NodeView patchNode(long projectId, long nodeId, NodePatch body, boolean fault) {
        if (fault) jdbc.queryForObject("SELECT 1/0", Integer.class);
        List<NodeView> rows = jdbc.query("UPDATE " + schema + ".node SET content=?, pos_x=COALESCE(?,pos_x), pos_y=COALESCE(?,pos_y), version=version+1 WHERE id=? AND project_id=? AND version=? RETURNING *",
                this::mapNode, body.content(), body.pos_x(), body.pos_y(), nodeId, projectId, body.expected_version());
        if (!rows.isEmpty()) return rows.getFirst();
        Integer exists = jdbc.queryForObject("SELECT count(*) FROM " + schema + ".node WHERE id=? AND project_id=?", Integer.class, nodeId, projectId);
        if (exists == null || exists == 0) throw new ApiException(HttpStatus.NOT_FOUND, "NODE_NOT_FOUND", "Node not found");
        throw new ApiException(HttpStatus.CONFLICT, "VERSION_CONFLICT", "Expected version does not match");
    }

    @Transactional
    ResetView reset(int nodes, boolean root) {
        jdbc.execute("TRUNCATE " + schema + ".node, " + schema + ".project_user_role, " + schema + ".project RESTART IDENTITY CASCADE");
        Long pid = jdbc.queryForObject("INSERT INTO " + schema + ".project(owner_id,name) VALUES (1,'benchmark') RETURNING id", Long.class);
        jdbc.update("INSERT INTO " + schema + ".project_user_role(project_id,user_id,role) VALUES (?,1,'OWNER')", pid);
        Long firstId = null;
        if (root) firstId = jdbc.queryForObject("INSERT INTO " + schema + ".node(project_id,author_id,content,state,depth,order_index,pos_x,pos_y) VALUES (?,1,'root','ACTIVE',0,0,0,0) RETURNING id", Long.class, pid);
        if (nodes > 0) {
            List<Long> ids = jdbc.queryForList("INSERT INTO " + schema + ".node(project_id,parent_id,author_id,content,state,depth,order_index,pos_x,pos_y) SELECT ?,?,1,'node-'||g,'ACTIVE',1,g,0,0 FROM generate_series(1,?) g RETURNING id", Long.class, pid, firstId, nodes);
            firstId = ids.getFirst();
        }
        return new ResetView(pid, firstId, nodes, root);
    }

    StateView state() {
        StateView partial = jdbc.queryForObject("SELECT count(*) FILTER (WHERE parent_id IS NULL AND state='ACTIVE') roots, count(*) nodes, COALESCE(max(version),0) max_version FROM " + schema + ".node",
                (rs, n) -> new StateView(rs.getLong("roots"), rs.getLong("nodes"), rs.getInt("max_version"), 0, 0));
        Long projects = jdbc.queryForObject("SELECT count(*) FROM " + schema + ".project", Long.class);
        Long memberships = jdbc.queryForObject("SELECT count(*) FROM " + schema + ".project_user_role", Long.class);
        return new StateView(partial.roots(), partial.nodes(), partial.max_version(), projects, memberships);
    }
}
