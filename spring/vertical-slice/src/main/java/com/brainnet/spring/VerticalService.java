package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.ApiModels.*;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Service
class VerticalService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;
    private final HttpClient aiHttp;
    private final String aiUrl;
    private final String aiKey;
    private final String aiModel;
    private final long aiTimeoutSeconds;

    VerticalService(
            JdbcTemplate jdbc,
            ObjectMapper mapper,
            PlatformTransactionManager transactionManager,
            @Value("${OPENAI_API_URL:https://api.openai.com/v1/chat/completions}") String aiUrl,
            @Value("${OPENAI_API_KEY:}") String aiKey,
            @Value("${OPENAI_MODEL:gpt-3.5-turbo}") String aiModel,
            @Value("${OPENAI_TIMEOUT_SECONDS:30}") long aiTimeoutSeconds) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        this.transaction = new TransactionTemplate(transactionManager);
        this.aiHttp = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(Math.max(1, aiTimeoutSeconds)))
                .build();
        this.aiUrl = aiUrl;
        this.aiKey = aiKey;
        this.aiModel = aiModel;
        this.aiTimeoutSeconds = Math.max(1, aiTimeoutSeconds);
    }

    record CreateResult(int status, List<NodeView> nodes) {}
    private record IdempotencyClaim(boolean fresh, String responseBody, Integer responseStatus) {}

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
                "SELECT count(*) FROM project_user_role WHERE project_id=? AND user_id=?",
                Integer.class, projectId, userId);
        if (member == null || member == 0) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "Not a project member");
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
        String key = normalizeIdempotencyKey(idempotencyKey);
        boolean ai = body.ai_prompt() != null && !body.ai_prompt().isBlank();
        if (!ai && (body.content() == null || body.content().isBlank())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "NODE_CONTENT_REQUIRED",
                    "content is required when ai_prompt is absent");
        }
        String requestHash = requestHash(body);
        IdempotencyClaim claim = key == null
                ? new IdempotencyClaim(true, null, null)
                : claimIdempotency(projectId, userId, key, requestHash);
        if (!claim.fresh()) {
            return new CreateResult(claim.responseStatus(), readNodes(claim.responseBody()));
        }

        try {
            String content = ai ? generateAiContent(body.ai_prompt()) : body.content();
            NodePersisted persisted = persistNode(
                    projectId, userId, body, content, ai ? "GHOST" : null, key, requestHash);
            return new CreateResult(HttpStatus.CREATED.value(), List.of(persisted.node()));
        } catch (RuntimeException ex) {
            if (key != null) releaseIdempotency(projectId, userId, key, requestHash);
            throw ex;
        }
    }

    private String normalizeIdempotencyKey(String value) {
        if (value == null) return null;
        if (value.isBlank() || value.length() > 128) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "IDEMPOTENCY_KEY_INVALID",
                    "Idempotency-Key must contain 1 to 128 characters");
        }
        return value;
    }

    private String requestHash(NodeCreate body) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(mapper.writeValueAsString(body).getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException("could not hash node request", ex);
        }
    }

    private IdempotencyClaim claimIdempotency(long projectId, long userId, String key, String requestHash) {
        return transaction.execute(status -> {
            int inserted = jdbc.update(
                    "INSERT INTO idempotency_request(actor_id,project_id,idempotency_key,request_hash,created_at,expires_at) "
                            + "VALUES (?,?,?, ?,now(),now()+interval '24 hours') "
                            + "ON CONFLICT (actor_id,idempotency_key) DO NOTHING",
                    userId, projectId, key, requestHash);
            if (inserted == 1) return new IdempotencyClaim(true, null, null);

            List<IdempotencyClaim> rows = jdbc.query(
                    "SELECT request_hash,response_status,response_body::text response_body "
                            + "FROM idempotency_request WHERE actor_id=? AND idempotency_key=?",
                    (rs, row) -> new IdempotencyClaim(
                            false, rs.getString("response_body"), (Integer) rs.getObject("response_status")),
                    userId, key);
            if (rows.isEmpty()) {
                throw new ApiException(HttpStatus.CONFLICT, "IDEMPOTENCY_IN_PROGRESS",
                        "Idempotency request is in progress");
            }
            IdempotencyClaim row = rows.getFirst();
            String storedHash = jdbc.queryForObject(
                    "SELECT request_hash FROM idempotency_request WHERE actor_id=? AND idempotency_key=?",
                    String.class, userId, key);
            if (!requestHash.equals(storedHash)) {
                throw new ApiException(HttpStatus.CONFLICT, "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency-Key was already used with a different request");
            }
            if (row.responseStatus() == null || row.responseBody() == null) {
                throw new ApiException(HttpStatus.CONFLICT, "IDEMPOTENCY_IN_PROGRESS",
                        "Idempotency request is in progress");
            }
            return row;
        });
    }

    private void releaseIdempotency(long projectId, long userId, String key, String requestHash) {
        transaction.executeWithoutResult(status -> jdbc.update(
                "DELETE FROM idempotency_request WHERE actor_id=? AND project_id=? AND idempotency_key=? AND request_hash=?",
                userId, projectId, key, requestHash));
    }

    private String generateAiContent(String prompt) {
        if (aiKey == null || aiKey.isBlank()) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "AI_PROVIDER_NOT_CONFIGURED",
                    "AI provider is not configured");
        }
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("model", aiModel);
            payload.put("messages", List.of(
                    Map.of("role", "system", "content", "당신은 창의적인 아이디어를 제공하는 도우미입니다."),
                    Map.of("role", "user", "content",
                            "다음 주제와 관련된 새로운 아이디어를 간략한 문장 형태로 한 개 작성해줘: " + prompt)));
            payload.put("max_tokens", 256);
            payload.put("temperature", 0.7);
            HttpRequest request = HttpRequest.newBuilder(URI.create(aiUrl))
                    .timeout(Duration.ofSeconds(aiTimeoutSeconds))
                    .header("Authorization", "Bearer " + aiKey)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(payload)))
                    .build();
            HttpResponse<String> response = aiHttp.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE",
                        "AI provider request failed");
            }
            JsonNode content = mapper.readTree(response.body()).path("choices").path(0).path("message").path("content");
            String answer = content.isMissingNode() ? null : content.asText();
            if (answer == null || answer.isBlank()) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE",
                        "AI provider request failed");
            }
            return answer.split("\\R", 2)[0].replaceFirst("^\\d+\\.\\s*", "").trim();
        } catch (HttpTimeoutException ex) {
            throw new ApiException(HttpStatus.GATEWAY_TIMEOUT, "AI_PROVIDER_TIMEOUT",
                    "AI provider request timed out");
        } catch (ApiException ex) {
            throw ex;
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE",
                    "AI provider request failed");
        } catch (IOException | RuntimeException ex) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE",
                    "AI provider request failed");
        }
    }

    private record NodePersisted(NodeView node) {}

    private NodePersisted persistNode(
            long projectId,
            long userId,
            NodeCreate body,
            String content,
            String forcedState,
            String idempotencyKey,
            String requestHash) {
        return transaction.execute(status -> {
            requireMember(projectId, userId);
            boolean isRoot = body.parent_id() == null || body.parent_id() == 0;
            Long parentId = isRoot ? null : body.parent_id();
            if (isRoot) {
                Integer existingRoot = jdbc.queryForObject(
                        "SELECT count(*) FROM node WHERE project_id=? AND parent_id IS NULL AND state='ACTIVE'",
                        Integer.class, projectId);
                if (existingRoot != null && existingRoot > 0) {
                    throw new ApiException(HttpStatus.CONFLICT, "ROOT_NODE_CONFLICT",
                            "Root node already exists for this project");
                }
            } else {
                Integer parent = jdbc.queryForObject(
                        "SELECT count(*) FROM node WHERE id=? AND project_id=?", Integer.class, parentId, projectId);
                if (parent == null || parent == 0) {
                    throw new ApiException(HttpStatus.NOT_FOUND, "PARENT_NODE_NOT_FOUND", "Parent node not found");
                }
                jdbc.query("SELECT id FROM node WHERE id=? AND project_id=? FOR KEY SHARE",
                        (rs, row) -> rs.getLong("id"), parentId, projectId);
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
                String eventId = UUID.randomUUID().toString();
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("event_id", eventId);
                payload.put("node_id", node.id());
                payload.put("project_id", projectId);
                payload.put("node", withTags);
                jdbc.update(
                        "INSERT INTO outbox_event(event_id,aggregate_type,aggregate_id,event_type,payload,occurred_at) "
                                + "VALUES (?,?,?,?,?::jsonb,now())",
                        eventId, "node", node.id(), "node.created", mapper.writeValueAsString(payload));

                if (idempotencyKey != null) {
                    String responseBody = mapper.writeValueAsString(List.of(withTags));
                    jdbc.update(
                            "UPDATE idempotency_request SET response_status=?,response_body=?::jsonb "
                                    + "WHERE actor_id=? AND project_id=? AND idempotency_key=? AND request_hash=?",
                            HttpStatus.CREATED.value(), responseBody, userId, projectId, idempotencyKey, requestHash);
                }
                return new NodePersisted(withTags);
            } catch (DuplicateKeyException ex) {
                if (isRoot) {
                    throw new ApiException(HttpStatus.CONFLICT, "ROOT_NODE_CONFLICT",
                            "Root node already exists for this project");
                }
                throw ex;
            }
        });
    }

    private List<NodeView> readNodes(String json) {
        try {
            JsonNode array = mapper.readTree(json);
            List<NodeView> nodes = new ArrayList<>();
            for (JsonNode node : array) nodes.add(nodeFromJson(node));
            return nodes;
        } catch (Exception ex) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "IDEMPOTENCY_RESPONSE_INVALID",
                    "Stored idempotency response is invalid");
        }
    }

    private NodeView nodeFromJson(JsonNode node) {
        List<Long> tags = new ArrayList<>();
        for (JsonNode tag : node.path("tags")) tags.add(tag.asLong());
        return new NodeView(
                node.path("id").asLong(), node.path("project_id").asLong(), nullableLong(node, "author_id"),
                nullableText(node, "content"), nullableText(node, "state"), node.path("depth").asInt(),
                node.path("order_index").asInt(), nullableDouble(node, "pos_x"), nullableDouble(node, "pos_y"),
                nullableLong(node, "parent_id"), nullableTime(node, "created_at"), nullableTime(node, "updated_at"),
                tags, node.path("version").asInt());
    }

    private Long nullableLong(JsonNode node, String name) { return node.path(name).isNull() ? null : node.path(name).asLong(); }
    private Double nullableDouble(JsonNode node, String name) { return node.path(name).isNull() ? null : node.path(name).asDouble(); }
    private String nullableText(JsonNode node, String name) { return node.path(name).isNull() ? null : node.path(name).asText(); }
    private OffsetDateTime nullableTime(JsonNode node, String name) {
        return node.path(name).isNull() ? null : OffsetDateTime.parse(node.path(name).asText());
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
        if (!updated.isEmpty()) return updated.getFirst();

        Integer exists = jdbc.queryForObject(
                "SELECT count(*) FROM node WHERE id=? AND project_id=?", Integer.class, nodeId, projectId);
        if (exists == null || exists == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NODE_NOT_FOUND", "Node not found");
        }
        throw new ApiException(HttpStatus.CONFLICT, "NODE_VERSION_CONFLICT", "Node version does not match expected_version");
    }
}
