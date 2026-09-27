package com.brainnet.spring;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
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
class RestMigrationIntegrationTest {
    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:15-alpine");

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("JWT_SECRET", () -> "rest-migration-integration-secret-at-least-32-bytes");
    }

    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper mapper;
    @Autowired ProjectService projects;
    private final HttpClient http = HttpClient.newHttpClient();
    private String token;
    private long userId;
    private long projectId;
    private long rootId;

    @BeforeEach
    void prepare() throws Exception {
        // Generated from Alembic head, including actual foreign keys, enums and lack of ORM-only defaults.
        jdbc.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public");
        try (var schema = getClass().getResourceAsStream("/alembic-head.sql")) {
            jdbc.execute(new String(schema.readAllBytes(), StandardCharsets.UTF_8));
        }
        var user = json(request("POST", "/auth/register", "{\"email\":\"owner@example.com\",\"password\":\"secret\"}", null), 201);
        userId = user.get("id").asLong();
        token = json(login("owner@example.com", "secret"), 200).get("access_token").asText();
        projectId = json(request("POST", "/projects", "{\"name\":\"test project\"}"), 201).get("id").asLong();
        rootId = jdbc.queryForObject("SELECT id FROM node WHERE project_id=?", Long.class, projectId);
    }

    @Test
    void accountContractsAndLegacyBcryptRemainCompatible() throws Exception {
        assertThat(json(request("GET", "/users/me", null), 200).get("id").asLong()).isEqualTo(userId);
        assertThat(request("GET", "/users/me", null, null).statusCode()).isEqualTo(401);
        assertThat(login("owner@example.com", "wrong").statusCode()).isEqualTo(401);
        assertThat(request("POST", "/auth/register", "{\"email\":\"owner@example.com\",\"password\":\"secret\"}", null).statusCode()).isEqualTo(409);
        assertThat(request("POST", "/auth/register", "{\"email\":\"invalid\",\"password\":\"secret\"}", null).statusCode()).isEqualTo(422);
        assertThat(request("POST", "/auth/register", "{\"email\":\"\",\"password\":\"secret\"}", null).statusCode()).isEqualTo(422);
        assertThat(request("POST", "/auth/login", "{}", null).statusCode()).isEqualTo(415);
        // A known bcrypt $2b$ hash produced by Python bcrypt for 'legacy-password'.
        jdbc.update("UPDATE app_user SET pw_hash=? WHERE id=?", LEGACY_HASH, userId);
        assertThat(login("owner@example.com", "legacy-password").statusCode()).isEqualTo(200);
    }

    @Test
    void projectsPreserveAtomicRootMembershipAndOwnerPermissions() throws Exception {
        assertThat(jdbc.queryForObject("SELECT count(*) FROM project_user_role WHERE project_id=? AND role='OWNER'", Long.class, projectId)).isEqualTo(1);
        var root = json(request("GET", path("/nodes/" + rootId), null), 200);
        assertThat(root.get("state").asText()).isEqualTo("ACTIVE");
        assertThat(root.get("content").asText()).isEqualTo("주제를 입력하세요");
        assertThat(root.get("pos_x").asDouble()).isEqualTo(800);
        assertThat(json(request("GET", "/projects?owned=true", null), 200)).hasSize(1);
        assertThat(json(request("PUT", path(""), "{\"name\":\"renamed\"}"), 200).get("name").asText()).isEqualTo("renamed");
        assertThat(request("POST", "/projects", "{}").statusCode()).isEqualTo(422);
        String outsider = secondUser();
        assertThat(request("GET", path("/nodes"), null, outsider).statusCode()).isEqualTo(403);
        assertThat(request("PATCH", path(""), "{\"name\":\"bad\"}", outsider).statusCode()).isEqualTo(403);
        assertThat(request("DELETE", path(""), null).statusCode()).isEqualTo(204);
        assertThat(request("GET", path(""), null).statusCode()).isEqualTo(404);
    }

    @Test
    void projectCreationRollsBackIfRootInsertFails() {
        jdbc.execute("CREATE FUNCTION reject_root() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test root failure'; END $$");
        jdbc.execute("CREATE TRIGGER reject_root BEFORE INSERT ON node FOR EACH ROW EXECUTE FUNCTION reject_root()");
        assertThatThrownBy(() -> projects.create(new ProjectService.Create("rollback", null), userId)).isInstanceOf(RuntimeException.class);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM project", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM project_user_role", Long.class)).isEqualTo(1);
    }

    @Test
    void nodeStateChangesTraverseDescendantsAndPreserveVersionsAndEvents() throws Exception {
        long child = child(rootId), grandchild = child(child);
        assertThat(request("POST", path("/nodes/" + child + "/activate"), null).statusCode()).isEqualTo(200);
        assertThat(jdbc.queryForList("SELECT version FROM node WHERE id IN (?,?)", Integer.class, child, grandchild)).containsExactly(1, 1);
        assertThat(request("POST", path("/nodes/" + child + "/activate"), null).statusCode()).isEqualTo(400);
        assertThat(request("POST", path("/nodes/" + child + "/deactivate"), null).statusCode()).isEqualTo(200);
        assertThat(jdbc.queryForObject("SELECT version FROM node WHERE id=?", Integer.class, grandchild)).isEqualTo(2);
        assertThat(request("DELETE", path("/nodes/" + child), null).statusCode()).isEqualTo(204);
        assertThat(json(request("GET", path("/nodes"), null), 200)).hasSize(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event WHERE event_type='node.deleted'", Long.class)).isEqualTo(1);
        assertThat(request("DELETE", path("/nodes/" + child), null).statusCode()).isEqualTo(404);
    }

    @Test
    void conflictingRootActivationRollsBackStateAndOutbox() throws Exception {
        long ghost = jdbc.queryForObject("INSERT INTO node(project_id,author_id,content,state,depth,order_index,created_at,updated_at) "
                + "VALUES (?,?,'ghost root','GHOST',0,0,now(),now()) RETURNING id", Long.class, projectId, userId);
        assertThat(request("POST", path("/nodes/" + ghost + "/activate"), null).statusCode()).isEqualTo(409);
        assertThat(jdbc.queryForObject("SELECT state::text FROM node WHERE id=?", String.class, ghost)).isEqualTo("GHOST");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event", Long.class)).isZero();
    }

    @Test
    void failedOutboxWriteRollsBackStateAndDeletion() throws Exception {
        long child = child(rootId);
        jdbc.execute("CREATE FUNCTION reject_event() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test event failure'; END $$");
        jdbc.execute("CREATE TRIGGER reject_event BEFORE INSERT ON outbox_event FOR EACH ROW EXECUTE FUNCTION reject_event()");
        assertThat(request("POST", path("/nodes/" + child + "/activate"), null).statusCode()).isEqualTo(500);
        assertThat(jdbc.queryForObject("SELECT state::text FROM node WHERE id=?", String.class, child)).isEqualTo("GHOST");
        assertThat(jdbc.queryForObject("SELECT version FROM node WHERE id=?", Integer.class, child)).isZero();
        assertThat(request("DELETE", path("/nodes/" + child), null).statusCode()).isEqualTo(500);
        assertThat(request("GET", path("/nodes/" + child), null).statusCode()).isEqualTo(200);
    }

    @Test
    void tagsAttachDetachAndFilterSubtreeWithinProject() throws Exception {
        long child = child(rootId), grandchild = child(child);
        long tag = tag();
        assertThat(request("POST", path("/tags/" + tag + "/nodes/" + child), null).statusCode()).isEqualTo(200);
        assertThat(request("POST", path("/tags/" + tag + "/nodes/" + child), null).statusCode()).isEqualTo(409);
        assertThat(json(request("GET", path("/tags/" + tag), null), 200).get("node_count").asLong()).isEqualTo(2);
        assertThat(json(request("GET", path("/nodes?tag_ids=" + tag + "," + tag), null), 200)).hasSize(2);
        assertThat(request("GET", path("/nodes?tag_ids=bad"), null).statusCode()).isEqualTo(422);
        long inherited = child(grandchild);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM tag_node WHERE tag_id=? AND node_id=?", Long.class, tag, inherited)).isEqualTo(1);
        assertThat(json(request("GET", "/users/me/tag-summaries", null), 200).get(0).get("nodes_contributed").asLong()).isEqualTo(3);
        assertThat(json(request("GET", path("/summary"), null), 200).get("total_nodes").asLong()).isEqualTo(4);
        long otherProject = json(request("POST", "/projects", "{\"name\":\"other\"}"), 201).get("id").asLong();
        assertThat(request("POST", "/projects/" + otherProject + "/tags/" + tag + "/nodes/" + rootId, null).statusCode()).isEqualTo(404);
        assertThat(request("DELETE", path("/tags/" + tag + "/nodes/" + child), null).statusCode()).isEqualTo(200);
        assertThat(request("DELETE", path("/tags/" + tag + "/nodes/" + child), null).statusCode()).isEqualTo(400);
        assertThat(json(request("PATCH", path("/tags/" + tag), "{\"name\":\"updated\"}"), 200).get("name").asText()).isEqualTo("updated");
        assertThat(request("POST", path("/tags/" + tag + "/nodes/" + rootId), null).statusCode()).isEqualTo(200);
        assertThat(request("DELETE", path("/tags/" + tag), null).statusCode()).isEqualTo(204);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM tag_node", Long.class)).isZero();
    }

    @Test
    void votesAreUniqueAndConfirmationWritesHistoryAndOutboxAtomically() throws Exception {
        long tag = tag();
        assertThat(request("POST", path("/tags/" + tag + "/vote"), null).statusCode()).isEqualTo(404);
        jdbc.update("INSERT INTO tag_summary(tag_id,summary_text,created_at) VALUES (?,'summary',now())", tag);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var responses = executor.invokeAll(List.of(
                    () -> request("POST", path("/tags/" + tag + "/vote"), null).statusCode(),
                    () -> request("POST", path("/tags/" + tag + "/vote"), null).statusCode()));
            assertThat(List.of(responses.get(0).get(), responses.get(1).get())).containsExactlyInAnyOrder(200, 400);
        }
        assertThat(request("POST", path("/votes/confirm?winning_tag_id=99999"), null).statusCode()).isEqualTo(404);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM vote", Long.class)).isEqualTo(1);
        var history = json(request("POST", path("/votes/confirm"), null), 200);
        assertThat(json(request("GET", path("/history"), null), 200)).hasSize(1);
        assertThat(json(request("GET", path("/history/" + history.get("id").asLong()), null), 200)).isEqualTo(history);
        assertThat(request("POST", path("/votes/confirm"), null).statusCode()).isEqualTo(409);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM vote", Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event WHERE aggregate_type='project' AND payload->>'node_id' IS NULL", Long.class)).isEqualTo(2);
    }

    @Test
    void preflightAndInvalidParametersUsePublicContracts() throws Exception {
        var preflight = http.send(HttpRequest.newBuilder(URI.create(base() + "/projects"))
                .header("Origin", "http://localhost:3000").header("Access-Control-Request-Method", "POST")
                .header("Access-Control-Request-Headers", "authorization,content-type,idempotency-key")
                .method("OPTIONS", HttpRequest.BodyPublishers.noBody()).build(), HttpResponse.BodyHandlers.ofString());
        assertThat(preflight.statusCode()).isEqualTo(200);
        assertThat(preflight.headers().firstValue("Access-Control-Allow-Origin")).contains("http://localhost:3000");
        var invalid = request("GET", "/projects/not-an-id", null);
        assertThat(json(invalid, 422).get("code").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(invalid.headers().firstValue("X-Trace-Id")).isPresent();
    }

    private long child(long parent) throws Exception {
        return json(request("POST", path("/nodes"), "{\"content\":\"child\",\"parent_id\":" + parent + "}"), 201).get(0).get("id").asLong();
    }
    private long tag() throws Exception {
        return json(request("POST", path("/tags"), "{\"name\":\"tag\",\"color\":\"#ff0000\"}"), 201).get("id").asLong();
    }
    private String secondUser() throws Exception {
        json(request("POST", "/auth/register", "{\"email\":\"other@example.com\",\"password\":\"secret\"}", null), 201);
        return json(login("other@example.com", "secret"), 200).get("access_token").asText();
    }
    private String path(String suffix) { return "/projects/" + projectId + suffix; }
    private String base() { return "http://localhost:" + port; }
    private JsonNode json(HttpResponse<String> response, int status) {
        assertThat(response.statusCode()).as(response.body()).isEqualTo(status);
        return mapper.readTree(response.body());
    }
    private HttpResponse<String> request(String method, String path, String body) throws Exception { return request(method, path, body, token); }
    private HttpResponse<String> request(String method, String path, String body, String auth) throws Exception {
        var request = HttpRequest.newBuilder(URI.create(base() + path)).header("Content-Type", "application/json");
        if (auth != null) request.header("Authorization", "Bearer " + auth);
        return http.send(request.method(method, body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
    }
    private HttpResponse<String> login(String email, String password) throws Exception {
        return http.send(HttpRequest.newBuilder(URI.create(base() + "/auth/login"))
                .header("Content-Type", "application/x-www-form-urlencoded")
                .POST(HttpRequest.BodyPublishers.ofString("username=" + email + "&password=" + password)).build(), HttpResponse.BodyHandlers.ofString());
    }
    private static final String LEGACY_HASH = "$2b$12$ooZKDhHNuLURdU4aOmAg6.rMAFj0nPLXjZdp4cnLXVjyOQPSUNcSa";
}
