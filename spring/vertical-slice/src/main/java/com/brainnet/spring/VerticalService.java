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
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

@Service
class VerticalService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;
    private final NodeIdempotencyService idempotency;
    private final NodeProviderService provider;
    private final NodeOutboxService outbox;

    VerticalService(JdbcTemplate jdbc, ObjectMapper mapper,
                    PlatformTransactionManager manager, NodeIdempotencyService idempotency,
                    NodeProviderService provider, NodeOutboxService outbox) {
        this.jdbc=jdbc; this.mapper=mapper; this.transaction=new TransactionTemplate(manager);
        this.idempotency=idempotency; this.provider=provider; this.outbox=outbox;
    }

    record CreateResult(int status, String body) {}

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
        List<Boolean> projects = jdbc.query(
                "SELECT p.is_deleted FROM project_user_role r JOIN project p ON p.id=r.project_id "
                        + "WHERE r.project_id=? AND r.user_id=?",
                (rs, row) -> rs.getBoolean("is_deleted"), projectId, userId);
        if (projects.isEmpty()) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "Not a project member");
        }
        if (projects.getFirst()) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Project not found");
        }
    }

    ProjectView getProject(long projectId, long userId) {
        requireMember(projectId, userId);
        List<ProjectView> projects = jdbc.query(
                "SELECT p.id,p.name,p.description,p.owner_id,p.created_at,p.updated_at,p.is_deleted,"
                        + "(SELECT count(*) FROM node WHERE project_id=p.id) node_count,"
                        + "(SELECT count(*) FROM tag WHERE project_id=p.id) tag_count "
                        + "FROM project p WHERE p.id=? AND p.is_deleted=false",
                (rs, row) -> new ProjectView(
                        rs.getLong("id"), rs.getString("name"), rs.getString("description"),
                        rs.getLong("owner_id"), timestamp(rs, "created_at"), timestamp(rs, "updated_at"),
                        rs.getBoolean("is_deleted"), null,
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

    CreateResult createNodes(long projectId, NodeCreate body, long userId, String idempotencyKey) {
        requireMember(projectId, userId);
        if (body == null) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Request validation failed");
        }
        boolean ai = body.ai_prompt() != null && !body.ai_prompt().isEmpty();
        if (!ai && (body.content() == null || body.content().isEmpty())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "NODE_CONTENT_REQUIRED",
                    "content is required when ai_prompt is absent");
        }
        NodeIdempotencyService.Claim claim = idempotency.claim(projectId, userId, idempotencyKey, body);
        if (claim != null && claim.responseBody() != null) {
            return creationResponse(claim.responseBody());
        }

        try {
            if (ai && body.parent_id() != null && body.parent_id() != 0) {
                Integer exists = jdbc.queryForObject("SELECT count(*) FROM node WHERE id=? AND project_id=?",
                        Integer.class, body.parent_id(), projectId);
                if (exists == null || exists == 0) {
                    throw new ApiException(HttpStatus.NOT_FOUND, "PARENT_NODE_NOT_FOUND", "Parent node not found");
                }
            }
            String content = ai ? provider.generateContent(body.ai_prompt()) : body.content();
            NodePersisted persisted = persistNode(
                    projectId, userId, body, content, ai ? "GHOST" : null, claim);
            return creationResponse(persisted.responseBody());
        } catch (RuntimeException ex) {
            idempotency.release(claim);
            throw ex;
        }
    }

    private CreateResult creationResponse(String json) {
        return new CreateResult(HttpStatus.CREATED.value(), mapper.writeValueAsString(mapper.readTree(json)));
    }

    private record NodePersisted(String responseBody) {}

    private NodePersisted persistNode(
            long projectId,
            long userId,
            NodeCreate body,
            String content,
            String forcedState,
            NodeIdempotencyService.Claim claim) {
        return transaction.execute(status -> {
            idempotency.lock(claim);
            requireMember(projectId, userId);
            boolean isRoot = body.parent_id() == null || body.parent_id() == 0;
            Long parentId = isRoot ? null : body.parent_id();
            if (isRoot && !"GHOST".equals(forcedState)) {
                Integer existingRoot = jdbc.queryForObject(
                        "SELECT count(*) FROM node WHERE project_id=? AND parent_id IS NULL AND state='ACTIVE'",
                        Integer.class, projectId);
                if (existingRoot != null && existingRoot > 0) {
                    throw new ApiException(HttpStatus.CONFLICT, "ROOT_NODE_CONFLICT",
                            "Root node already exists for this project");
                }
            } else if (!isRoot) {
                var parents = jdbc.query("SELECT id FROM node WHERE id=? AND project_id=? FOR KEY SHARE",
                        (rs, row) -> rs.getLong("id"), parentId, projectId);
                if (parents.isEmpty()) {
                    throw new ApiException(HttpStatus.NOT_FOUND, "PARENT_NODE_NOT_FOUND", "Parent node not found");
                }
            }

            String stateValue = forcedState != null ? forcedState : (isRoot ? "ACTIVE" : "GHOST");
            try {
                List<NodeView> inserted = jdbc.query(
                        "INSERT INTO node(project_id,parent_id,author_id,content,state,depth,order_index,pos_x,pos_y,created_at,updated_at) "
                                + "VALUES (?,?,?,?,?::node_state_t,?,?,?,?,now(),now()) RETURNING id,project_id,author_id,content,state,depth,order_index,pos_x,pos_y,parent_id,created_at,updated_at,version",
                        this::nodeWithoutTags,
                        projectId, parentId, userId, content, stateValue,
                        body.depth() == null ? 0 : body.depth(), body.order() == null ? 0 : body.order(),
                        body.pos_x() == null ? 0.0 : body.pos_x(), body.pos_y() == null ? 0.0 : body.pos_y());
                NodeView node = inserted.getFirst();
                if (parentId != null) {
                    jdbc.update("INSERT INTO tag_node(tag_id,node_id) SELECT tag_id,? FROM tag_node WHERE node_id=? "
                                    + "ON CONFLICT DO NOTHING", node.id(), parentId);
                }
                NodeView withTags = withTags(node);
                outbox.append(projectId, node.id(), "node.created", Map.of("node", withTags));

                String responseBody = idempotency.complete(claim, mapper.writeValueAsString(List.of(withTags)));
                return new NodePersisted(responseBody);
            } catch (DuplicateKeyException ex) {
                if (isRoot) {
                    throw new ApiException(HttpStatus.CONFLICT, "ROOT_NODE_CONFLICT",
                            "Root node already exists for this project");
                }
                throw ex;
            }
        });
    }

    @Transactional
    NodeView patchNode(long projectId, long nodeId, NodePatch body, long userId) {
        requireMember(projectId, userId);
        if (body == null) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Request validation failed");
        }
        if (body.expected_version() == null) {
            if (!body.hasChanges()) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR",
                        "Request validation failed", List.of(Map.of(
                                "type", "value_error",
                                "loc", List.of("body"),
                                "msg", "Value error, at least one node field must be provided",
                                "input", Map.of(),
                                "ctx", Map.of("error", Map.of()))));
            }
            throw new ApiException(HttpStatus.PRECONDITION_REQUIRED, "NODE_VERSION_REQUIRED", "expected_version is required");
        }
        if (body.expected_version() < 0) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR",
                    "Request validation failed", List.of(Map.of(
                            "type", "greater_than_equal",
                            "loc", List.of("body", "expected_version"),
                            "msg", "Input should be greater than or equal to 0",
                            "input", body.expected_version(),
                            "ctx", Map.of("ge", 0))));
        }
        if (!body.hasChanges()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR",
                    "Request validation failed", List.of(Map.of(
                            "type", "value_error",
                            "loc", List.of("body"),
                            "msg", "Value error, at least one node field must be provided",
                            "input", Map.of("expected_version", body.expected_version()),
                            "ctx", Map.of("error", Map.of()))));
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
        if (!updated.isEmpty()) {
            outbox.append(projectId, nodeId, "node.updated", Map.of());
            return updated.getFirst();
        }

        Integer exists = jdbc.queryForObject(
                "SELECT count(*) FROM node WHERE id=? AND project_id=?", Integer.class, nodeId, projectId);
        if (exists == null || exists == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NODE_NOT_FOUND", "Node not found");
        }
        throw new ApiException(HttpStatus.CONFLICT, "NODE_VERSION_CONFLICT", "Node version does not match expected_version");
    }
}
