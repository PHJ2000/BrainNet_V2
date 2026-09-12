package com.brainnet.spring;

import static org.assertj.core.api.Assertions.assertThat;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import java.net.URI;
import java.net.InetSocketAddress;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterAll;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import org.springframework.mock.web.MockHttpServletRequest;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ExtendWith(OutputCaptureExtension.class)
class VerticalSliceIntegrationTest {
    private static final String SECRET = "spring-integration-secret-at-least-32-bytes-long";
    private static HttpServer PROVIDER;

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:15-alpine")
            .withDatabaseName("brainnet")
            .withUsername("brainnet")
            .withPassword("brainnet");

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        try {
            PROVIDER = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            PROVIDER.createContext("/v1/chat/completions", VerticalSliceIntegrationTest::providerResponse);
            PROVIDER.start();
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("JWT_SECRET", () -> SECRET);
        registry.add("OPENAI_API_KEY", () -> "test-key");
        registry.add("OPENAI_API_URL", () -> "http://127.0.0.1:" + PROVIDER.getAddress().getPort() + "/v1/chat/completions");
        registry.add("OPENAI_TIMEOUT_SECONDS", () -> "2");
    }

    @AfterAll
    static void stopProvider() {
        if (PROVIDER != null) PROVIDER.stop(0);
    }

    private static void providerResponse(HttpExchange exchange) throws java.io.IOException {
        exchange.getRequestBody().readAllBytes();
        byte[] body = "{\"choices\":[{\"message\":{\"content\":\"1. generated idea\"}}]}"
                .getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, body.length);
        try (var output = exchange.getResponseBody()) {
            output.write(body);
        }
    }

    @LocalServerPort
    int port;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    NodeIdempotencyService idempotency;

    @Autowired
    org.springframework.transaction.PlatformTransactionManager transactionManager;

    private final HttpClient http = HttpClient.newHttpClient();

    @BeforeEach
    void prepareSchema() {
        jdbc.execute("CREATE TABLE IF NOT EXISTS project (id BIGINT PRIMARY KEY, owner_id BIGINT NOT NULL, name VARCHAR(120) NOT NULL, description TEXT, is_deleted BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())");
        jdbc.execute("CREATE TABLE IF NOT EXISTS project_user_role (project_id BIGINT NOT NULL, user_id BIGINT NOT NULL, role VARCHAR(16) NOT NULL, PRIMARY KEY(project_id,user_id))");
        jdbc.execute("DO $$ BEGIN CREATE TYPE node_state_t AS ENUM ('GHOST','ACTIVE','ARCHIVED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$");
        jdbc.execute("CREATE TABLE IF NOT EXISTS node (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, project_id BIGINT NOT NULL, parent_id BIGINT, author_id BIGINT, content TEXT NOT NULL, state node_state_t NOT NULL, depth INT NOT NULL, order_index INT NOT NULL, pos_x DOUBLE PRECISION, pos_y DOUBLE PRECISION, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), version INT NOT NULL DEFAULT 0)");
        jdbc.execute("CREATE TABLE IF NOT EXISTS tag (id BIGINT PRIMARY KEY, project_id BIGINT NOT NULL)");
        jdbc.execute("CREATE TABLE IF NOT EXISTS tag_node (tag_id BIGINT NOT NULL, node_id BIGINT NOT NULL, PRIMARY KEY(tag_id,node_id))");
        jdbc.execute("CREATE TABLE IF NOT EXISTS idempotency_request (id BIGSERIAL PRIMARY KEY, actor_id BIGINT NOT NULL, project_id BIGINT NOT NULL, idempotency_key VARCHAR(128) NOT NULL, request_hash VARCHAR(64) NOT NULL, response_status INT, response_body JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL, UNIQUE(actor_id,idempotency_key))");
        jdbc.execute("CREATE TABLE IF NOT EXISTS outbox_event (id BIGSERIAL PRIMARY KEY, event_id VARCHAR(36) NOT NULL UNIQUE, aggregate_type VARCHAR(64) NOT NULL, aggregate_id BIGINT NOT NULL, event_type VARCHAR(128) NOT NULL, payload JSONB NOT NULL, occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(), published_at TIMESTAMPTZ, attempt_count INT NOT NULL DEFAULT 0, lease_until TIMESTAMPTZ, last_error TEXT)");
        jdbc.execute("TRUNCATE outbox_event, idempotency_request, tag_node, tag, node, project_user_role, project");
        jdbc.update("INSERT INTO project(id,owner_id,name,description) VALUES (1,7,'demo','slice')");
        jdbc.update("INSERT INTO project(id,owner_id,name,description,is_deleted) VALUES (2,7,'deleted','slice',true)");
        jdbc.update("INSERT INTO project_user_role(project_id,user_id,role) VALUES (1,7,'OWNER')");
        jdbc.update("INSERT INTO project_user_role(project_id,user_id,role) VALUES (2,7,'OWNER')");
        jdbc.update("INSERT INTO node(id,project_id,author_id,content,state,depth,order_index,pos_x,pos_y) VALUES (11,1,7,'before','ACTIVE',0,0,1,2)");
        jdbc.update("INSERT INTO tag(id,project_id) VALUES (101,1)");
        jdbc.update("INSERT INTO tag_node(tag_id,node_id) VALUES (101,11)");
    }

    @Test
    void createsRegularNodeAndWritesOutboxAtomically() throws Exception {
        HttpResponse<String> response = request("POST", "/projects/1/nodes", bearer(7),
                "{\"content\":\"child\",\"parent_id\":11,\"depth\":1,\"order\":2,\"pos_x\":3.5,\"pos_y\":4.5,\"state\":\"GHOST\"}",
                "post-regular");
        assertThat(response.statusCode()).isEqualTo(201);
        assertThat(response.body()).contains("\"state\":\"GHOST\"")
                .contains("\"content\":\"child\"")
                .contains("\"parent_id\":11")
                .contains("\"tags\":[101]");
        Long nodeId = jdbc.queryForObject("SELECT id FROM node WHERE content='child'", Long.class);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event WHERE aggregate_id=? AND event_type='node.created'", Long.class, nodeId))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT payload::text FROM outbox_event WHERE aggregate_id=?", String.class, nodeId))
                .contains("\"node_id\":");
    }

    @Test
    void createsAiNodeThroughProviderAndStoresGhostOutboxEvent() throws Exception {
        HttpResponse<String> response = requestWithIdempotency("POST", "/projects/1/nodes", bearer(7),
                "{\"ai_prompt\":\"brainstorm\",\"parent_id\":11,\"depth\":2,\"order\":3}", "ai-idem-1");
        assertThat(response.statusCode()).isEqualTo(201);
        assertThat(response.body()).contains("\"content\":\"generated idea\"")
                .contains("\"state\":\"GHOST\"")
                .contains("\"parent_id\":11");
        Long nodeId = jdbc.queryForObject("SELECT id FROM node WHERE content='generated idea'", Long.class);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event WHERE aggregate_id=? AND event_type='node.created'", Long.class, nodeId))
                .isEqualTo(1);
    }

    @Test
    void idempotencyReturnsCachedResponseWithoutDuplicateNodeOrOutbox() throws Exception {
        String body = "{\"content\":\"same\",\"parent_id\":11}";
        HttpResponse<String> first = requestWithIdempotency("POST", "/projects/1/nodes", bearer(7), body, "idem-1");
        HttpResponse<String> second = requestWithIdempotency("POST", "/projects/1/nodes", bearer(7), body, "idem-1");
        assertThat(first.statusCode()).isEqualTo(201);
        assertThat(second.statusCode()).isEqualTo(201);
        assertThat(second.body()).isEqualTo(first.body());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node WHERE content='same'", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event WHERE event_type='node.created'", Long.class)).isEqualTo(1);

        HttpResponse<String> cached = requestWithIdempotency("POST", "/projects/1/nodes", bearer(7), body, "idem-1");
        assertThat(cached.statusCode()).isEqualTo(201);
        assertThat(cached.body()).isEqualTo(second.body());
    }

    @Test
    void expiredIdempotencyClaimCanBeReused() throws Exception {
        jdbc.update(
                "INSERT INTO idempotency_request(actor_id,project_id,idempotency_key,request_hash,response_status,response_body,created_at,expires_at) "
                        + "VALUES (7,1,'expired-idem',repeat('0',64),201,'[]'::jsonb,now()-interval '2 days',now()-interval '1 second')");

        HttpResponse<String> response = requestWithIdempotency(
                "POST", "/projects/1/nodes", bearer(7), "{\"content\":\"after-expiry\",\"parent_id\":11}", "expired-idem");

        assertThat(response.statusCode()).isEqualTo(201);
        assertThat(response.body()).contains("\"content\":\"after-expiry\"");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node WHERE content='after-expiry'", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT response_status FROM idempotency_request WHERE idempotency_key='expired-idem'", Integer.class))
                .isEqualTo(201);
    }

    @Test
    void sameKeyCannotReplayAnotherProjectsResponse() throws Exception {
        jdbc.update("INSERT INTO project(id,owner_id,name) VALUES (3,7,'other')");
        jdbc.update("INSERT INTO project_user_role(project_id,user_id,role) VALUES (3,7,'OWNER')");
        String body = "{\"content\":\"scoped\",\"parent_id\":11}";
        assertThat(requestWithIdempotency("POST", "/projects/1/nodes", bearer(7), body, "scoped").statusCode())
                .isEqualTo(201);
        var reused = requestWithIdempotency("POST", "/projects/3/nodes", bearer(7), body, "scoped");
        assertThat(reused.statusCode()).isEqualTo(409);
        assertThat(reused.body()).contains("IDEMPOTENCY_KEY_REUSED");
    }

    @Test
    void concurrentSameKeyCreatesOneNodeAndOneEvent() throws Exception {
        String token = bearer(7);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            List<Future<HttpResponse<String>>> requests = new ArrayList<>();
            for (int index = 0; index < 30; index++) {
                requests.add(executor.submit(() -> requestWithIdempotency("POST", "/projects/1/nodes", token,
                        "{\"content\":\"same-key-concurrent\",\"parent_id\":11}", "concurrent-key")));
            }
            int successes = 0;
            for (var request : requests) {
                var response = request.get();
                assertThat(response.statusCode()).isIn(201, 409);
                if (response.statusCode() == 201) successes++;
                else assertThat(response.body()).contains("IDEMPOTENCY_IN_PROGRESS");
            }
            assertThat(successes).isPositive();
        }
        assertThat(jdbc.queryForObject("SELECT count(*) FROM node WHERE content='same-key-concurrent'", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event", Long.class)).isEqualTo(1);
    }

    @Test
    void staleOwnerCannotReleaseOrFinishReclaimedRequest() {
        var body = new ApiModels.NodeCreate("lease", null, 11L, null, null, null, null, null);
        var old = idempotency.claim(1, 7, "lease", body);
        jdbc.update("UPDATE idempotency_request SET expires_at=now()-interval '1 second' WHERE id=?", old.id());
        var replacement = idempotency.claim(1, 7, "lease", body);
        assertThat(replacement.id()).isNotEqualTo(old.id());
        var transaction = new org.springframework.transaction.support.TransactionTemplate(transactionManager);
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> transaction.executeWithoutResult(status -> idempotency.lock(old)))
                .isInstanceOf(ApiExceptionHandler.ApiException.class);
        idempotency.release(old);
        transaction.executeWithoutResult(status -> idempotency.lock(replacement));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM idempotency_request WHERE id=?", Long.class, replacement.id())).isEqualTo(1);
    }

    @Test
    void outboxFailureRollsBackNodeAndReleasesClaim() throws Exception {
        jdbc.execute("ALTER TABLE outbox_event ADD CONSTRAINT reject_test_event CHECK (event_type <> 'node.created')");
        try {
            var response = requestWithIdempotency("POST", "/projects/1/nodes", bearer(7),
                    "{\"content\":\"atomic-failure\",\"parent_id\":11}", "atomic-failure");
            assertThat(response.statusCode()).isEqualTo(500);
            assertThat(jdbc.queryForObject("SELECT count(*) FROM node WHERE content='atomic-failure'", Long.class)).isZero();
            assertThat(jdbc.queryForObject("SELECT count(*) FROM idempotency_request", Long.class)).isZero();
        } finally {
            jdbc.execute("ALTER TABLE outbox_event DROP CONSTRAINT reject_test_event");
        }
    }

    @Test
    void readsProjectAndNodeWithMembershipAndTraceContract() throws Exception {
        HttpResponse<String> project = request("GET", "/projects/1", bearer(7), null, "slice-read-1");
        assertThat(project.statusCode()).isEqualTo(200);
        assertThat(project.headers().firstValue("X-Trace-Id")).contains("slice-read-1");
        assertThat(project.body()).contains("\"member_count\":null").contains("\"node_count\":1");

        HttpResponse<String> node = request("GET", "/projects/1/nodes/11", bearer(7), null, null);
        assertThat(node.statusCode()).isEqualTo(200);
        assertThat(node.body()).contains("\"version\":0").contains("\"tags\":[101]");
    }

    @Test
    void patchIncrementsVersionAndRejectsStaleVersion() throws Exception {
        HttpResponse<String> updated = request("PATCH", "/projects/1/nodes/11", bearer(7),
                "{\"expected_version\":0,\"content\":\"after\"}", "slice-patch-1");
        assertThat(updated.statusCode()).isEqualTo(200);
        assertThat(updated.headers().firstValue("X-Trace-Id")).contains("slice-patch-1");
        assertThat(updated.body()).contains("\"content\":\"after\"").contains("\"version\":1");

        HttpResponse<String> stale = request("PATCH", "/projects/1/nodes/11", bearer(7),
                "{\"expected_version\":0,\"content\":\"stale\"}", null);
        assertThat(stale.statusCode()).isEqualTo(409);
        assertThat(stale.body()).contains("\"code\":\"NODE_VERSION_CONFLICT\"");
    }

    @Test
    void concurrentPatchesAllowExactlyOneWinner() throws Exception {
        int writers = 100;
        ExecutorService pool = Executors.newFixedThreadPool(writers);
        try {
            List<Future<Integer>> results = new ArrayList<>();
            for (int i = 0; i < writers; i++) {
                String content = "writer-" + i;
                results.add(pool.submit(() -> request("PATCH", "/projects/1/nodes/11", bearer(7),
                        "{\"expected_version\":0,\"content\":\"" + content + "\"}", null).statusCode()));
            }
            long successes = 0;
            long conflicts = 0;
            for (Future<Integer> result : results) {
                int status = result.get();
                if (status == 200) successes++;
                if (status == 409) conflicts++;
            }
            assertThat(successes).isEqualTo(1);
            assertThat(conflicts).isEqualTo(writers - 1);
            assertThat(jdbc.queryForObject("SELECT version FROM node WHERE id=11", Integer.class)).isEqualTo(1);
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    void rejectsNonMemberAndMissingVersion() throws Exception {
        HttpResponse<String> forbidden = request("GET", "/projects/1/nodes/11", bearer(8), null, null);
        assertThat(forbidden.statusCode()).isEqualTo(403);
        assertThat(forbidden.body()).contains("\"code\":\"FORBIDDEN\"");

        HttpResponse<String> missingVersion = request("PATCH", "/projects/1/nodes/11", bearer(7),
                "{\"content\":\"unsafe\"}", null);
        assertThat(missingVersion.statusCode()).isEqualTo(428);
        assertThat(missingVersion.body()).contains("\"code\":\"NODE_VERSION_REQUIRED\"");
    }

    @Test
    void preservesLegacyProjectAndPatchValidationContract() throws Exception {
        HttpResponse<String> deleted = request("GET", "/projects/2", bearer(7), null, "deleted-project");
        assertThat(deleted.statusCode()).isEqualTo(404);
        assertThat(deleted.body()).contains("\"code\":\"NOT_FOUND\"");

        HttpResponse<String> emptyPatch = request("PATCH", "/projects/1/nodes/11", bearer(7), "{}", "empty-patch");
        assertThat(emptyPatch.statusCode()).isEqualTo(422);
        assertThat(emptyPatch.body()).contains("\"code\":\"VALIDATION_ERROR\"")
                .contains("\"message\":\"Request validation failed\"")
                .contains("\"errors\"")
                .contains("\"type\":\"value_error\"")
                .contains("\"loc\":[\"body\"]")
                .contains("Value error, at least one node field must be provided")
                .contains("\"input\":{}")
                .contains("\"ctx\":{\"error\":{}");

        HttpResponse<String> negativeVersion = request("PATCH", "/projects/1/nodes/11", bearer(7),
                "{\"expected_version\":-1,\"content\":\"invalid\"}", "negative-version");
        assertThat(negativeVersion.statusCode()).isEqualTo(422);
        assertThat(negativeVersion.body()).contains("\"code\":\"VALIDATION_ERROR\"")
                .contains("\"message\":\"Request validation failed\"")
                .contains("\"type\":\"greater_than_equal\"")
                .contains("\"loc\":[\"body\",\"expected_version\"]")
                .contains("Input should be greater than or equal to 0")
                .contains("\"input\":-1")
                .contains("\"ctx\":{\"ge\":0}");
    }

    @Test
    void preservesLegacyPatchTagResponseShape() throws Exception {
        HttpResponse<String> updated = request("PATCH", "/projects/1/nodes/11", bearer(7),
                "{\"expected_version\":0,\"content\":\"after\"}", "patch-tags");
        assertThat(updated.statusCode()).isEqualTo(200);
        assertThat(updated.body()).contains("\"tags\":[]");
    }

    @Test
    void missingAuthenticationUsesLegacyBearerChallenge() throws Exception {
        HttpResponse<String> response = request("GET", "/projects/1", null, null, "missing-auth");
        assertThat(response.statusCode()).isEqualTo(401);
        assertThat(response.headers().firstValue("WWW-Authenticate")).contains("Bearer");
        assertThat(response.body()).contains("\"message\":\"Not authenticated\"");
    }

    @Test
    void emitsTraceCorrelatedErrorLogs(CapturedOutput output) throws Exception {
        HttpResponse<String> response = request("GET", "/projects/1/nodes/999", bearer(7), null, "log-proof");
        assertThat(response.statusCode()).isEqualTo(404);
        assertThat(output.getOut()).contains("request_error status=404 code=NODE_NOT_FOUND trace_id=log-proof")
                .contains("request_complete trace_id=log-proof");
    }

    @Test
    void rejectsInvalidTokenWithTrace() throws Exception {
        HttpResponse<String> response = request("GET", "/projects/1", "Bearer invalid", null, "auth-check");
        assertThat(response.statusCode()).isEqualTo(401);
        assertThat(response.headers().firstValue("X-Trace-Id")).contains("auth-check");
        assertThat(response.body()).contains("\"code\":\"UNAUTHORIZED\"");
    }

    @Test
    void preservesDownstreamNotFoundErrorAfterAuthentication() throws Exception {
        HttpResponse<String> response = request("GET", "/projects/1/nodes/999", bearer(7), null, "missing-node");
        assertThat(response.statusCode()).isEqualTo(404);
        assertThat(response.headers().firstValue("X-Trace-Id")).contains("missing-node");
        assertThat(response.body()).contains("\"code\":\"NODE_NOT_FOUND\"");
    }

    @Test
    void mapsDatabaseFailureToStableTraceableError(CapturedOutput output) {
        HttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute(TraceFilter.ATTRIBUTE, "database-error-trace");

        ApiExceptionHandler handler = new ApiExceptionHandler();
        var response = handler.database(
                new DataAccessResourceFailureException("database failure must not leak"), request);

        assertThat(response.getStatusCode().value()).isEqualTo(500);
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("database-error-trace");
        assertThat(response.getBody()).isEqualTo(
                new ApiModels.ErrorView("DB_ERROR", "database operation failed", "database-error-trace"));
        assertThat(output.getOut()).contains(
                "request_error status=500 code=DB_ERROR trace_id=database-error-trace")
                .doesNotContain("database failure must not leak");
    }

    private HttpResponse<String> request(String method, String path, String authorization, String body, String trace)
            throws Exception {
        return requestWithIdempotency(method, path, authorization, body, null, trace);
    }

    private HttpResponse<String> requestWithIdempotency(
            String method, String path, String authorization, String body, String idempotencyKey)
            throws Exception {
        return requestWithIdempotency(method, path, authorization, body, idempotencyKey, null);
    }

    private HttpResponse<String> requestWithIdempotency(
            String method, String path, String authorization, String body, String idempotencyKey, String trace)
            throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + port + path));
        if (authorization != null) {
            builder.header("Authorization", authorization);
        }
        if (idempotencyKey != null) {
            builder.header("Idempotency-Key", idempotencyKey);
        }
        if (trace != null) {
            builder.header("X-Trace-Id", trace);
        }
        if (body == null) {
            builder.method(method, HttpRequest.BodyPublishers.noBody());
        } else {
            builder.header("Content-Type", "application/json");
            builder.method(method, HttpRequest.BodyPublishers.ofString(body));
        }
        return http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static String bearer(long userId) throws Exception {
        SignedJWT jwt = new SignedJWT(
                new JWSHeader(JWSAlgorithm.HS256),
                new JWTClaimsSet.Builder()
                        .subject(Long.toString(userId))
                        .expirationTime(Date.from(Instant.now().plusSeconds(300)))
                        .build());
        jwt.sign(new MACSigner(SECRET.getBytes(StandardCharsets.UTF_8)));
        return "Bearer " + jwt.serialize();
    }
}
