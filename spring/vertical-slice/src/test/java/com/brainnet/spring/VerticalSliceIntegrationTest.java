package com.brainnet.spring;

import static org.assertj.core.api.Assertions.assertThat;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import java.net.URI;
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

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class VerticalSliceIntegrationTest {
    private static final String SECRET = "spring-integration-secret-at-least-32-bytes-long";

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:15-alpine")
            .withDatabaseName("brainnet")
            .withUsername("brainnet")
            .withPassword("brainnet");

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("JWT_SECRET", () -> SECRET);
    }

    @LocalServerPort
    int port;

    @Autowired
    JdbcTemplate jdbc;

    private final HttpClient http = HttpClient.newHttpClient();

    @BeforeEach
    void prepareSchema() {
        jdbc.execute("CREATE TABLE IF NOT EXISTS project (id BIGINT PRIMARY KEY, owner_id BIGINT NOT NULL, name VARCHAR(120) NOT NULL, description TEXT, is_deleted BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())");
        jdbc.execute("CREATE TABLE IF NOT EXISTS project_user_role (project_id BIGINT NOT NULL, user_id BIGINT NOT NULL, role VARCHAR(16) NOT NULL, PRIMARY KEY(project_id,user_id))");
        jdbc.execute("CREATE TABLE IF NOT EXISTS node (id BIGINT PRIMARY KEY, project_id BIGINT NOT NULL, parent_id BIGINT, author_id BIGINT, content TEXT NOT NULL, state VARCHAR(16) NOT NULL, depth INT NOT NULL, order_index INT NOT NULL, pos_x DOUBLE PRECISION, pos_y DOUBLE PRECISION, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), version INT NOT NULL DEFAULT 0)");
        jdbc.execute("CREATE TABLE IF NOT EXISTS tag (id BIGINT PRIMARY KEY, project_id BIGINT NOT NULL)");
        jdbc.execute("CREATE TABLE IF NOT EXISTS tag_node (tag_id BIGINT NOT NULL, node_id BIGINT NOT NULL, PRIMARY KEY(tag_id,node_id))");
        jdbc.execute("TRUNCATE tag_node, tag, node, project_user_role, project");
        jdbc.update("INSERT INTO project(id,owner_id,name,description) VALUES (1,7,'demo','slice')");
        jdbc.update("INSERT INTO project_user_role(project_id,user_id,role) VALUES (1,7,'OWNER')");
        jdbc.update("INSERT INTO node(id,project_id,author_id,content,state,depth,order_index,pos_x,pos_y) VALUES (11,1,7,'before','ACTIVE',0,0,1,2)");
        jdbc.update("INSERT INTO tag(id,project_id) VALUES (101,1)");
        jdbc.update("INSERT INTO tag_node(tag_id,node_id) VALUES (101,11)");
    }

    @Test
    void readsProjectAndNodeWithMembershipAndTraceContract() throws Exception {
        HttpResponse<String> project = request("GET", "/projects/1", bearer(7), null, "slice-read-1");
        assertThat(project.statusCode()).isEqualTo(200);
        assertThat(project.headers().firstValue("X-Trace-Id")).contains("slice-read-1");
        assertThat(project.body()).contains("\"node_count\":1");

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
        ExecutorService pool = Executors.newFixedThreadPool(20);
        try {
            List<Future<Integer>> results = new ArrayList<>();
            for (int i = 0; i < 20; i++) {
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
            assertThat(conflicts).isEqualTo(19);
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

    private HttpResponse<String> request(String method, String path, String authorization, String body, String trace)
            throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + port + path))
                .header("Authorization", authorization);
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
