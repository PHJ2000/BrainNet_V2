package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.ApiModels.*;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class VerticalService {
    private final JdbcTemplate jdbc;

    VerticalService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static OffsetDateTime timestamp(ResultSet rs, String column) throws SQLException {
        Timestamp value = rs.getTimestamp(column);
        return value == null ? null : value.toInstant().atOffset(ZoneOffset.UTC);
    }

    private NodeView nodeWithoutTags(ResultSet rs, int ignored) throws SQLException {
        return new NodeView(
                rs.getLong("id"),
                rs.getLong("project_id"),
                (Long) rs.getObject("author_id"),
                rs.getString("content"),
                rs.getString("state"),
                rs.getInt("depth"),
                rs.getInt("order_index"),
                (Double) rs.getObject("pos_x"),
                (Double) rs.getObject("pos_y"),
                (Long) rs.getObject("parent_id"),
                timestamp(rs, "created_at"),
                timestamp(rs, "updated_at"),
                List.of(),
                rs.getInt("version"));
    }

    private NodeView withTags(NodeView node) {
        List<Long> tags = jdbc.query(
                "SELECT tag_id FROM tag_node WHERE node_id=? ORDER BY tag_id",
                (tagRs, tagRow) -> tagRs.getLong("tag_id"), node.id());
        return new NodeView(node.id(), node.project_id(), node.author_id(), node.content(), node.state(),
                node.depth(), node.order_index(), node.pos_x(), node.pos_y(), node.parent_id(),
                node.created_at(), node.updated_at(), tags, node.version());
    }

    private void requireMember(long projectId, long userId) {
        Integer member = jdbc.queryForObject(
                "SELECT count(*) FROM project_user_role pur "
                        + "JOIN project p ON p.id=pur.project_id "
                        + "WHERE pur.project_id=? AND pur.user_id=? AND p.is_deleted=false",
                Integer.class, projectId, userId);
        if (member == null || member == 0) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "Not a project member");
        }
    }

    ProjectView getProject(long projectId, long userId) {
        requireMember(projectId, userId);
        List<ProjectView> projects = jdbc.query(
                "SELECT p.id,p.name,p.description,p.owner_id,p.created_at,p.updated_at,p.is_deleted,"
                        + "(SELECT count(*) FROM project_user_role WHERE project_id=p.id) member_count,"
                        + "(SELECT count(*) FROM node WHERE project_id=p.id) node_count,"
                        + "(SELECT count(*) FROM tag WHERE project_id=p.id) tag_count "
                        + "FROM project p WHERE p.id=? AND p.is_deleted=false",
                (rs, row) -> new ProjectView(
                        rs.getLong("id"), rs.getString("name"), rs.getString("description"),
                        rs.getLong("owner_id"), timestamp(rs, "created_at"), timestamp(rs, "updated_at"),
                        rs.getBoolean("is_deleted"), rs.getLong("member_count"),
                        rs.getLong("node_count"), rs.getLong("tag_count")), projectId);
        if (projects.isEmpty()) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Project not found");
        }
        return projects.getFirst();
    }

    NodeView getNode(long projectId, long nodeId, long userId) {
        requireMember(projectId, userId);
        List<NodeView> nodes = jdbc.query(
                "SELECT id,project_id,author_id,content,state,depth,order_index,pos_x,pos_y,parent_id,"
                        + "created_at,updated_at,version FROM node WHERE id=? AND project_id=?",
                this::nodeWithoutTags, nodeId, projectId);
        if (nodes.isEmpty()) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NODE_NOT_FOUND", "Node not found");
        }
        return withTags(nodes.getFirst());
    }

    @Transactional
    NodeView patchNode(long projectId, long nodeId, NodePatch body, long userId) {
        requireMember(projectId, userId);
        if (body.expected_version() == null) {
            throw new ApiException(HttpStatus.PRECONDITION_REQUIRED, "NODE_VERSION_REQUIRED", "expected_version is required");
        }
        if (body.expected_version() < 0 || !body.hasChanges()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "A node field must be provided");
        }

        List<String> changes = new ArrayList<>();
        List<Object> args = new ArrayList<>();
        if (body.content() != null) { changes.add("content=?"); args.add(body.content()); }
        if (body.pos_x() != null) { changes.add("pos_x=?"); args.add(body.pos_x()); }
        if (body.pos_y() != null) { changes.add("pos_y=?"); args.add(body.pos_y()); }
        if (body.depth() != null) { changes.add("depth=?"); args.add(body.depth()); }
        if (body.order() != null) { changes.add("order_index=?"); args.add(body.order()); }
        changes.add("version=version+1");
        changes.add("updated_at=now()");
        args.add(nodeId);
        args.add(projectId);
        args.add(body.expected_version());

        String sql = "UPDATE node SET " + String.join(",", changes)
                + " WHERE id=? AND project_id=? AND version=? RETURNING id,project_id,author_id,content,state,depth,order_index,pos_x,pos_y,parent_id,created_at,updated_at,version";
        List<NodeView> updated = jdbc.query(sql, this::nodeWithoutTags, args.toArray());
        if (!updated.isEmpty()) return withTags(updated.getFirst());

        Integer exists = jdbc.queryForObject(
                "SELECT count(*) FROM node WHERE id=? AND project_id=?", Integer.class, nodeId, projectId);
        if (exists == null || exists == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NODE_NOT_FOUND", "Node not found");
        }
        throw new ApiException(HttpStatus.CONFLICT, "NODE_VERSION_CONFLICT", "Node version does not match expected_version");
    }
}
