package com.brainnet.spring;

import static org.assertj.core.api.Assertions.assertThat;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class BackendOperationsIntegrationTest {
    @Container static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:15-alpine");
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("JWT_SECRET", () -> "backend-operations-local-integration-secret");
    }
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper mapper;
    @Autowired com.zaxxer.hikari.HikariDataSource dataSource;
    private final HttpClient http = HttpClient.newHttpClient();
    private String owner, editor;
    private long ownerId, editorId, projectId, rootId;

    @BeforeEach void prepare() throws Exception {
        if (dataSource.getHikariPoolMXBean() != null) dataSource.getHikariPoolMXBean().softEvictConnections();
        jdbc.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public");
        try (var schema = getClass().getResourceAsStream("/alembic-head.sql")) {
            jdbc.execute(new String(schema.readAllBytes(), StandardCharsets.UTF_8));
        }
        owner = account("owner@example.com"); editor = account("editor@example.com");
        ownerId = json(request("GET", "/users/me", null, owner), 200).get("id").asLong();
        editorId = json(request("GET", "/users/me", null, editor), 200).get("id").asLong();
        projectId = json(request("POST", "/projects", "{\"name\":\"operations\"}", owner), 201).get("id").asLong();
        rootId = jdbc.queryForObject("SELECT id FROM node WHERE project_id=?", Long.class, projectId);
        jdbc.update("INSERT INTO project_user_role(project_id,user_id,role,invited_at,accepted_at) VALUES (?,?,'EDITOR',now(),now())", projectId, editorId);
    }

    @Test void contentHistoryRestoresIntoANewVersionWithoutChangingCoordinatesOrState() throws Exception {
        assertThat(json(request("GET", path("/nodes/" + rootId + "/versions"), null, editor), 200)).hasSize(1);
        json(request("PATCH", path("/nodes/" + rootId), "{\"content\":\"first\",\"expected_version\":0}", editor), 200);
        json(request("PATCH", path("/nodes/" + rootId), "{\"content\":\"second\",\"pos_x\":99,\"expected_version\":1}", owner), 200);
        var first = json(request("GET", path("/nodes/" + rootId + "/versions/1"), null, owner), 200);
        assertThat(first.get("content").asText()).isEqualTo("first");
        assertThat(first.get("author_id").asLong()).isEqualTo(editorId);
        var restored = json(request("POST", path("/nodes/" + rootId + "/versions/1/restore"), "{\"expected_version\":2}", owner), 200);
        assertThat(restored.get("version").asInt()).isEqualTo(3);
        assertThat(restored.get("content").asText()).isEqualTo("first");
        assertThat(restored.get("pos_x").asDouble()).isEqualTo(99);
        assertThat(restored.get("state").asText()).isEqualTo("ACTIVE");
        assertThat(json(request("GET", path("/nodes/" + rootId + "/versions"), null, editor), 200)).hasSize(4);
        assertThat(json(request("GET", path("/nodes/" + rootId + "/versions?before_version=2&limit=1"), null, editor), 200).get(0).get("version_no").asInt()).isEqualTo(1);
        assertThat(request("POST", path("/nodes/" + rootId + "/versions/1/restore"), "{\"expected_version\":2}", owner).statusCode()).isEqualTo(409);
        assertThat(request("POST", path("/nodes/" + rootId + "/versions/1/restore"), "{}", owner).statusCode()).isEqualTo(428);
        assertThat(request("POST", path("/nodes/" + rootId + "/versions/1/restore"), "{\"expected_version\":-1}", owner).statusCode()).isEqualTo(422);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM activity_log WHERE type='NODE_RESTORE'", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event WHERE event_type='node.updated'", Long.class)).isEqualTo(3);
    }

    @Test void simultaneousEditAndRestoreHaveExactlyOneWinner() throws Exception {
        json(request("PATCH", path("/nodes/" + rootId), "{\"content\":\"edited\",\"expected_version\":0}", owner), 200);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var jobs = executor.invokeAll(List.of(
                    () -> request("PATCH", path("/nodes/" + rootId), "{\"content\":\"racing edit\",\"expected_version\":1}", editor).statusCode(),
                    () -> request("POST", path("/nodes/" + rootId + "/versions/0/restore"), "{\"expected_version\":1}", owner).statusCode()));
            assertThat(List.of(jobs.get(0).get(), jobs.get(1).get())).containsExactlyInAnyOrder(200, 409);
        }
        assertThat(jdbc.queryForObject("SELECT version FROM node WHERE id=?", Integer.class, rootId)).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node_version WHERE node_id=?", Long.class, rootId)).isEqualTo(3);
    }

    @Test void legacyBaselineIsCapturedAndDeletionRemovesVersionsAndMetrics() throws Exception {
        jdbc.update("DELETE FROM node_version WHERE node_id=?", rootId);
        json(request("PATCH", path("/nodes/" + rootId), "{\"content\":\"new\",\"expected_version\":0}", owner), 200);
        var baseline = json(request("GET", path("/nodes/" + rootId + "/versions/0"), null, owner), 200);
        assertThat(baseline.get("content").asText()).isEqualTo("주제를 입력하세요");
        assertThat(baseline.get("author_id").isNull()).isTrue();
        long child = child(rootId, true);
        json(request("GET", path("/nodes/" + child + "/metrics"), null, editor), 200);
        assertThat(request("DELETE", path("/nodes/" + child), null, owner).statusCode()).isEqualTo(204);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node_version WHERE node_id=?", Long.class, child)).isZero();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node_metrics WHERE node_id=?", Long.class, child)).isZero();
        assertThat(request("GET", path("/nodes/" + child + "/versions"), null, owner).statusCode()).isEqualTo(404);
    }

    @Test void metricsTrackSubtreeCreationStateAndDeletion() throws Exception {
        long child = child(rootId, false), grandchild = child(child, true);
        var metric = json(request("GET", path("/nodes/" + rootId + "/metrics"), null, editor), 200);
        assertThat(metric.get("subtree_size").asInt()).isEqualTo(3);
        assertThat(metric.get("density_score").asDouble()).isCloseTo(2.0/3, org.assertj.core.data.Offset.offset(0.00001));
        var all = json(request("GET", path("/metrics"), null, editor), 200);
        assertThat(all).hasSize(3);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node_metrics", Long.class)).isEqualTo(3);
        json(request("POST", path("/nodes/" + child + "/deactivate"), null, owner), 200);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node_metrics", Long.class)).isZero();
        metric = json(request("GET", path("/nodes/" + rootId + "/metrics"), null, owner), 200);
        assertThat(metric.get("density_score").asDouble()).isCloseTo(1.0/3, org.assertj.core.data.Offset.offset(0.00001));
        assertThat(request("DELETE", path("/nodes/" + child), null, owner).statusCode()).isEqualTo(204);
        metric = json(request("GET", path("/nodes/" + rootId + "/metrics"), null, owner), 200);
        assertThat(metric.get("subtree_size").asInt()).isEqualTo(1);
        assertThat(metric.get("density_score").asDouble()).isEqualTo(1);
        assertThat(request("GET", path("/nodes/" + grandchild + "/metrics"), null, owner).statusCode()).isEqualTo(404);
    }

    @Test void activitiesArePagedScopedAndRecordActorsWithoutContents() throws Exception {
        long child = child(rootId, false);
        json(request("PATCH", path("/nodes/" + child), "{\"content\":\"private-node-content\",\"expected_version\":0}", editor), 200);
        var logs = json(request("GET", path("/activities?limit=2"), null, owner), 200);
        assertThat(logs).hasSize(2);
        assertThat(logs.get(0).get("type").asText()).isEqualTo("NODE_UPDATE");
        assertThat(logs.get(0).get("user_id").asLong()).isEqualTo(editorId);
        assertThat(logs.toString()).doesNotContain("private-node-content");
        long before = logs.get(1).get("id").asLong();
        var page = json(request("GET", path("/activities?before_id=" + before), null, editor), 200);
        assertThat(page.get(0).get("id").asLong()).isLessThan(before);
        assertThat(json(request("GET", path("/activities?type=NODE_UPDATE"), null, owner), 200)).hasSize(1);
        assertThat(request("GET", path("/activities?type=unknown"), null, owner).statusCode()).isEqualTo(422);
        assertThat(request("GET", path("/activities?limit=101"), null, owner).statusCode()).isEqualTo(422);
    }

    @Test void activityFailureRollsBackMutationVersionMetricInvalidationAndEvents() throws Exception {
        json(request("GET", path("/metrics"), null, owner), 200);
        jdbc.execute("CREATE FUNCTION reject_activity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test audit failure'; END $$");
        jdbc.execute("CREATE TRIGGER reject_activity BEFORE INSERT ON activity_log FOR EACH ROW EXECUTE FUNCTION reject_activity()");
        assertThat(request("PATCH", path("/nodes/" + rootId), "{\"content\":\"failed\",\"expected_version\":0}", editor).statusCode()).isEqualTo(500);
        assertThat(jdbc.queryForObject("SELECT version FROM node WHERE id=?", Integer.class, rootId)).isZero();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node_version", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node_metrics", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event", Long.class)).isZero();
        assertThat(request("PATCH", path("/members/" + editorId), "{\"role\":\"OWNER\"}", owner).statusCode()).isEqualTo(500);
        assertThat(jdbc.queryForObject("SELECT owner_id FROM project WHERE id=?", Long.class, projectId)).isEqualTo(ownerId);
        assertThat(jdbc.queryForObject("SELECT role::text FROM project_user_role WHERE user_id=? AND project_id=?", String.class, editorId, projectId)).isEqualTo("EDITOR");
    }

    @Test void existingActivitiesWithUnknownActorAndNullPayloadRemainReadable() throws Exception {
        jdbc.update("INSERT INTO activity_log(user_id,project_id,type,payload,logged_at) VALUES (null,?,'NODE_UPDATE',null,now())", projectId);
        var event = json(request("GET", path("/activities?limit=1"), null, editor), 200).get(0);
        assertThat(event.get("payload").isNull()).isTrue();
        assertThat(event.get("user_id").isNull()).isTrue();
    }

    @Test void ownershipTransferAndLeavingEnforceSoleOwnerAndRevokeAccess() throws Exception {
        assertThat(json(request("GET", path("/members"), null, editor), 200)).hasSize(2);
        assertThat(request("DELETE", path("/members/me"), null, owner).statusCode()).isEqualTo(409);
        assertThat(request("DELETE", path("/members/" + ownerId), null, owner).statusCode()).isEqualTo(409);
        assertThat(request("DELETE", path("/members/" + ownerId), null, editor).statusCode()).isEqualTo(403);
        assertThat(request("PATCH", path("/members/" + ownerId), "{\"role\":\"EDITOR\"}", owner).statusCode()).isEqualTo(409);
        assertThat(request("PATCH", path("/members/" + editorId), "{\"role\":\"VIEWER\"}", owner).statusCode()).isEqualTo(422);
        var promoted = json(request("PATCH", path("/members/" + editorId), "{\"role\":\"OWNER\"}", owner), 200);
        assertThat(promoted.get("role").asText()).isEqualTo("OWNER");
        assertThat(json(request("GET", path(""), null, editor), 200).get("owner_id").asLong()).isEqualTo(editorId);
        assertThat(json(request("GET", "/projects?owned=true", null, owner), 200)).isEmpty();
        assertThat(json(request("GET", "/projects?owned=true", null, editor), 200)).hasSize(1);
        assertThat(request("PATCH", path(""), "{\"name\":\"forbidden\"}", owner).statusCode()).isEqualTo(403);
        assertThat(request("DELETE", path("/members/me"), null, owner).statusCode()).isEqualTo(204);
        for (String suffix : List.of("/nodes", "/members", "/activities", "/metrics", "/nodes/" + rootId + "/versions")) {
            assertThat(request("GET", path(suffix), null, owner).statusCode()).isEqualTo(403);
        }
        assertThat(jdbc.queryForObject("SELECT count(*) FROM project_user_role WHERE project_id=? AND role='OWNER'", Long.class, projectId)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event WHERE event_type='membership.changed'", Long.class)).isEqualTo(2);
    }

    @Test void removalCleansOnlyThatMembersCurrentVotesAndPreservesTheirNodes() throws Exception {
        var node = json(request("POST", path("/nodes"), "{\"content\":\"member idea\",\"parent_id\":" + rootId + "}", editor), 201).get(0);
        long child = node.get("id").asLong();
        json(request("POST", path("/nodes/" + child + "/activate"), null, editor), 200);
        long tag = json(request("POST", path("/tags"), "{\"name\":\"vote tag\"}", owner), 201).get("id").asLong();
        json(request("POST", path("/tags/" + tag + "/nodes/" + child), null, owner), 200);
        json(request("POST", path("/tags/" + tag + "/summary"), null, owner), 200);
        json(request("POST", path("/tags/" + tag + "/vote"), null, editor), 200);
        json(request("POST", path("/tags/" + tag + "/vote"), null, owner), 200);
        assertThat(request("DELETE", path("/members/" + editorId), null, owner).statusCode()).isEqualTo(204);
        assertThat(jdbc.queryForList("SELECT voter_id FROM vote", Long.class)).containsExactly(ownerId);
        assertThat(json(request("GET", path("/nodes/" + child), null, owner), 200).get("author_id").asLong()).isEqualTo(editorId);
        assertThat(request("PATCH", path("/nodes/" + child), "{\"content\":\"unauthorized\",\"expected_version\":1}", editor).statusCode()).isEqualTo(403);
        assertThat(request("POST", path("/tags/" + tag + "/vote"), null, editor).statusCode()).isEqualTo(403);
    }

    @Test void concurrentOwnershipTransfersHaveOneWinner() throws Exception {
        String third = account("third@example.com");
        long thirdId = json(request("GET", "/users/me", null, third), 200).get("id").asLong();
        jdbc.update("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES (?,?,'EDITOR',now())", projectId, thirdId);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var jobs = executor.invokeAll(List.of(
                    () -> request("PATCH", path("/members/" + editorId), "{\"role\":\"OWNER\"}", owner).statusCode(),
                    () -> request("PATCH", path("/members/" + thirdId), "{\"role\":\"OWNER\"}", owner).statusCode()));
            assertThat(List.of(jobs.get(0).get(), jobs.get(1).get())).containsExactlyInAnyOrder(200, 403);
        }
        assertThat(jdbc.queryForObject("SELECT count(*) FROM project_user_role WHERE project_id=? AND role='OWNER'", Long.class, projectId)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT owner_id FROM project WHERE id=?", Long.class, projectId))
                .isEqualTo(jdbc.queryForObject("SELECT user_id FROM project_user_role WHERE project_id=? AND role='OWNER'", Long.class, projectId));
    }

    @Test void newEndpointsRejectOtherProjectsAndDeletedProjects() throws Exception {
        String outsider = account("outsider@example.com");
        for (String suffix : List.of("/members", "/metrics", "/activities", "/nodes/" + rootId + "/versions")) {
            assertThat(request("GET", path(suffix), null, outsider).statusCode()).isEqualTo(403);
        }
        long otherProject = json(request("POST", "/projects", "{\"name\":\"other\"}", owner), 201).get("id").asLong();
        assertThat(request("GET", "/projects/" + otherProject + "/nodes/" + rootId + "/versions", null, owner).statusCode()).isEqualTo(404);
        assertThat(request("GET", "/projects/" + otherProject + "/nodes/" + rootId + "/metrics", null, owner).statusCode()).isEqualTo(404);
        assertThat(request("DELETE", path(""), null, owner).statusCode()).isEqualTo(204);
        for (String suffix : List.of("/members", "/metrics", "/activities", "/nodes/" + rootId + "/versions", "/nodes")) {
            assertThat(request("GET", path(suffix), null, editor).statusCode()).isEqualTo(404);
        }
        assertThat(json(request("GET", "/projects", null, editor), 200)).isEmpty();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event WHERE event_type='project.deleted'", Long.class)).isEqualTo(1);
    }

    private long child(long parent, boolean active) throws Exception {
        long id = json(request("POST", path("/nodes"), "{\"content\":\"child\",\"parent_id\":" + parent + "}", owner), 201).get(0).get("id").asLong();
        if (active) json(request("POST", path("/nodes/" + id + "/activate"), null, owner), 200);
        return id;
    }
    private String account(String email) throws Exception {
        json(request("POST", "/auth/register", "{\"email\":\"" + email + "\",\"password\":\"secret\"}", null), 201);
        return json(http.send(HttpRequest.newBuilder(URI.create(base() + "/auth/login"))
                .header("Content-Type", "application/x-www-form-urlencoded")
                .POST(HttpRequest.BodyPublishers.ofString("username=" + email + "&password=secret")).build(), HttpResponse.BodyHandlers.ofString()), 200)
                .get("access_token").asText();
    }
    private String path(String suffix) { return "/projects/" + projectId + suffix; }
    private String base() { return "http://localhost:" + port; }
    private HttpResponse<String> request(String method, String path, String body, String token) throws Exception {
        var request = HttpRequest.newBuilder(URI.create(base() + path)).header("Content-Type", "application/json");
        if (token != null) request.header("Authorization", "Bearer " + token);
        return http.send(request.method(method, body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
    }
    private JsonNode json(HttpResponse<String> response, int status) {
        assertThat(response.statusCode()).as(response.body()).isEqualTo(status);
        return mapper.readTree(response.body());
    }
}
