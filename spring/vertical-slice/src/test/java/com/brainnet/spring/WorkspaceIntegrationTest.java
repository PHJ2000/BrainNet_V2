package com.brainnet.spring;

import static org.assertj.core.api.Assertions.*;

import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import tools.jackson.databind.*;

import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

@Testcontainers
@SpringBootTest(
        properties = "AI_QUEUE_ENABLED=false",
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class WorkspaceIntegrationTest {
    @Container
    static final PostgreSQLContainer<?> DB = new PostgreSQLContainer<>("postgres:15-alpine");

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url", DB::getJdbcUrl);
        r.add("spring.datasource.username", DB::getUsername);
        r.add("spring.datasource.password", DB::getPassword);
        r.add("JWT_SECRET", () -> "spring-workspace-isolated-verification-key-32");
    }

    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper json;
    @Autowired WorkspaceProposalService proposals;
    @Autowired NodeIdempotencyService claims;
    final HttpClient http = HttpClient.newHttpClient();
    String owner, viewer;
    long pid, root, viewerId;

    @BeforeEach
    void setup() throws Exception {
        jdbc.execute("TRUNCATE app_user CASCADE");
        owner = account("owner@example.com");
        viewer = account("viewer@example.com");
        viewerId = body(call("GET", "/users/me", null, viewer, null), 200).get("id").asLong();
        pid =
                body(call("POST", "/projects", Map.of("name", "Workspace"), owner, null), 201)
                        .get("id")
                        .asLong();
        root = jdbc.queryForObject("SELECT id FROM node WHERE project_id=?", Long.class, pid);
        jdbc.update(
                "INSERT INTO project_user_role(project_id,user_id,role,invited_at)"
                        + " VALUES(?,?,'VIEWER',now())",
                pid,
                viewerId);
    }

    String path(String suffix) {
        return "/projects/" + pid + suffix;
    }

    String account(String email) throws Exception {
        body(
                call(
                        "POST",
                        "/auth/register",
                        Map.of("email", email, "password", "secret"),
                        null,
                        null),
                201);
        var req =
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/auth/login"))
                        .header("Content-Type", "application/x-www-form-urlencoded")
                        .POST(
                                HttpRequest.BodyPublishers.ofString(
                                        "username=" + email + "&password=secret"))
                        .build();
        return body(http.send(req, HttpResponse.BodyHandlers.ofString()), 200)
                .get("access_token")
                .asText();
    }

    HttpResponse<String> call(String method, String path, Object data, String token, String key)
            throws Exception {
        var r =
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + path))
                        .header("Content-Type", "application/json");
        if (token != null) r.header("Authorization", "Bearer " + token);
        if (key != null) r.header("Idempotency-Key", key);
        return http.send(
                r.method(
                                method,
                                data == null
                                        ? HttpRequest.BodyPublishers.noBody()
                                        : HttpRequest.BodyPublishers.ofString(
                                                data instanceof String t
                                                        ? t
                                                        : json.writeValueAsString(data)))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
    }

    JsonNode body(HttpResponse<String> r, int status) {
        assertThat(r.statusCode()).as(r.body()).isEqualTo(status);
        return json.readTree(r.body());
    }

    JsonNode task(String title) throws Exception {
        return body(
                call(
                        "POST",
                        path("/tasks"),
                        Map.of("id", UUID.randomUUID().toString(), "title", title, "node_id", root),
                        owner,
                        null),
                201);
    }

    Map<String, Object> patch(JsonNode t, String status) {
        var b = new LinkedHashMap<String, Object>();
        b.put("title", t.get("title").asText());
        b.put("body", "");
        b.put("status", status);
        b.put("expected_version", t.get("version").asInt());
        if (t.hasNonNull("due_date")) b.put("due_date", t.get("due_date").asText());
        return b;
    }

    @Test
    void typedTaskCommandsPreserveOmittedFieldsAndRejectInvalidJsonTypes() throws Exception {
        String id = UUID.randomUUID().toString();
        var checklist =
                List.of(Map.of("id", UUID.randomUUID().toString(), "text", "확인", "done", false));
        var created =
                body(
                        call(
                                "POST",
                                path("/tasks"),
                                Map.of(
                                        "id",
                                        id,
                                        "title",
                                        "타입 계약",
                                        "checklist",
                                        checklist,
                                        "repeat_every_days",
                                        7,
                                        "due_date",
                                        "2026-10-15"),
                                owner,
                                null),
                        201);
        assertThat(json.convertValue(created, Map.class).keySet())
                .containsExactlyInAnyOrder(
                        "id",
                        "project_id",
                        "creator_id",
                        "title",
                        "body",
                        "status",
                        "priority",
                        "assignee_id",
                        "due_date",
                        "node_id",
                        "checklist",
                        "repeat_every_days",
                        "recurrence_parent_id",
                        "version",
                        "created_at",
                        "updated_at");
        var command = new LinkedHashMap<String, Object>();
        command.put("title", "변경");
        command.put("due_date", "2026-10-15");
        command.put("expected_version", 0);
        var updated = body(call("PUT", path("/tasks/" + id), command, owner, null), 200);
        assertThat(updated.get("checklist")).isEqualTo(created.get("checklist"));
        assertThat(updated.get("repeat_every_days").asInt()).isEqualTo(7);
        command.put("expected_version", 1);
        command.put("repeat_every_days", null);
        updated = body(call("PUT", path("/tasks/" + id), command, owner, null), 200);
        assertThat(updated.get("repeat_every_days").isNull()).isTrue();
        assertThat(updated.get("checklist")).isEqualTo(created.get("checklist"));
        command.put("expected_version", 2);
        command.put("checklist", null);
        assertThat(call("PUT", path("/tasks/" + id), command, owner, null).statusCode())
                .isEqualTo(422);
        command.put("checklist", List.of());
        command.put("expected_version", "2");
        assertThat(call("PUT", path("/tasks/" + id), command, owner, null).statusCode())
                .isEqualTo(422);
        command.put("expected_version", 2);
        command.put("unexpected", true);
        assertThat(call("PUT", path("/tasks/" + id), command, owner, null).statusCode())
                .isEqualTo(422);
        command.remove("unexpected");
        command.put("title", true);
        assertThat(call("PUT", path("/tasks/" + id), command, owner, null).statusCode())
                .isEqualTo(422);
        command.put("title", "완료");
        updated = body(call("PUT", path("/tasks/" + id), command, owner, null), 200);
        assertThat(updated.get("checklist").size()).isZero();
        assertThat(updated.get("version").asInt()).isEqualTo(3);
    }

    @Test
    void typedQueriesKeepPaginationAndPublicResponsesExcludeInternalState() throws Exception {
        var first = task("첫 과제");
        var second = task("다음 과제");
        var page = body(call("GET", path("/tasks?limit=1"), null, owner, null), 200);
        assertThat(page.get("items").size()).isEqualTo(1);
        assertThat(page.get("next_cursor").asText()).isEqualTo(second.get("id").asText());
        var next =
                body(
                        call(
                                "GET",
                                path("/tasks?limit=1&before=" + page.get("next_cursor").asText()),
                                null,
                                owner,
                                null),
                        200);
        assertThat(next.get("items").get(0).get("id")).isEqualTo(first.get("id"));
        assertThat(next.get("next_cursor").isNull()).isTrue();
        for (String endpoint :
                List.of(
                        path("/tasks"),
                        path("/discussions"),
                        path("/operations"),
                        "/workspace/tasks",
                        "/workspace/knowledge")) {
            assertThat(call("GET", endpoint + "?limit=invalid", null, owner, null).statusCode())
                    .as(endpoint)
                    .isEqualTo(422);
        }
        assertThat(call("GET", path("/overview?today=invalid"), null, owner, null).statusCode())
                .isEqualTo(422);
        var proposal =
                body(
                        call(
                                "POST",
                                path("/proposals?enqueue=true"),
                                Map.of(
                                        "id",
                                        UUID.randomUUID().toString(),
                                        "mode",
                                        "SUMMARY",
                                        "node_ids",
                                        List.of(root)),
                                owner,
                                null),
                        201);
        assertThat(proposal.has("request_hash")).isFalse();
        assertThat(proposal.has("lease_token")).isFalse();
        assertThat(proposal.get("sources").get(0).get("id").asLong()).isEqualTo(root);
        assertThat(proposal.get("status").asText()).isEqualTo("QUEUED");
    }

    @Test
    void nullMentionsAndSourceIdsReturnValidationErrors() throws Exception {
        String thread = UUID.randomUUID().toString();
        body(
                call("POST", path("/discussions"), Map.of("id", thread, "body", "토론"), owner, null),
                201);
        var withNull = Collections.singletonList(null);
        assertThat(
                        call(
                                        "POST",
                                        path("/discussions/" + thread + "/replies"),
                                        Map.of(
                                                "id",
                                                UUID.randomUUID().toString(),
                                                "body",
                                                "답글",
                                                "mentions",
                                                withNull),
                                        owner,
                                        null)
                                .statusCode())
                .isEqualTo(422);
        assertThat(
                        call(
                                        "POST",
                                        path("/proposals?enqueue=true"),
                                        Map.of(
                                                "id",
                                                UUID.randomUUID().toString(),
                                                "mode",
                                                "SUMMARY",
                                                "node_ids",
                                                withNull),
                                        owner,
                                        null)
                                .statusCode())
                .isEqualTo(422);
    }

    @Test
    void staleProposalRecoveryHonorsTheProjectLock() throws Exception {
        String id = UUID.randomUUID().toString();
        long uid = jdbc.queryForObject("SELECT owner_id FROM project WHERE id=?", Long.class, pid);
        jdbc.update(
                "INSERT INTO"
                    + " ai_proposal(id,project_id,actor_id,mode,instruction,sources,status,request_hash,lease_token,created_at,updated_at)"
                    + " VALUES(?,?,?,'SUMMARY','','[]','RUNNING','request','lease',now(),now()-interval"
                    + " '2 minutes')",
                id,
                pid,
                uid);
        try (var gate =
                java.sql.DriverManager.getConnection(
                        DB.getJdbcUrl(), DB.getUsername(), DB.getPassword())) {
            gate.setAutoCommit(false);
            try (var query =
                    gate.prepareStatement("SELECT id FROM project WHERE id=? FOR UPDATE")) {
                query.setLong(1, pid);
                query.executeQuery().close();
            }
            proposals.poll();
            assertThat(
                            jdbc.queryForObject(
                                    "SELECT status FROM ai_proposal WHERE id=?", String.class, id))
                    .isEqualTo("RUNNING");
            gate.rollback();
        }
        proposals.poll();
        assertThat(
                        jdbc.queryForObject(
                                "SELECT status FROM ai_proposal WHERE id=?", String.class, id))
                .isEqualTo("INTERRUPTED");
        assertThat(
                        jdbc.queryForObject(
                                "SELECT lease_token FROM ai_proposal WHERE id=?", String.class, id))
                .isNull();
    }

    @Test
    void metricsReadsDoNotInvalidateUndoOrDeletePreviewsButEditsDo() throws Exception {
        body(
                call(
                        "PATCH",
                        path("/nodes/" + root),
                        Map.of("content", "변경", "expected_version", 0),
                        owner,
                        null),
                200);
        String operation =
                body(call("GET", path("/operations"), null, owner, null), 200)
                        .get("items")
                        .get(0)
                        .get("id")
                        .asText();
        // Existing V3/Spring receipts may contain cached metrics. They must remain usable too.
        jdbc.update(
                "UPDATE node_operation SET"
                    + " \"after\"=jsonb_set(\"after\",'{metrics}','[{\"computed_at\":\"old-cache\"}]')"
                    + " WHERE id=?",
                operation);
        var preview =
                body(
                        call(
                                "GET",
                                path("/operations/" + operation + "/preview"),
                                null,
                                owner,
                                null),
                        200);
        body(call("GET", path("/metrics"), null, owner, null), 200);
        var refreshed =
                body(
                        call(
                                "GET",
                                path("/operations/" + operation + "/preview"),
                                null,
                                owner,
                                null),
                        200);
        assertThat(refreshed.get("preview_hash")).isEqualTo(preview.get("preview_hash"));
        body(
                call(
                        "POST",
                        path("/operations/" + operation + "/undo"),
                        Map.of("preview_hash", preview.get("preview_hash").asText()),
                        owner,
                        "metrics-undo"),
                200);
        var delete =
                body(
                        call("GET", path("/nodes/" + root + "/delete-preview"), null, owner, null),
                        200);
        body(call("GET", path("/metrics"), null, owner, null), 200);
        assertThat(
                        body(
                                        call(
                                                "GET",
                                                path("/nodes/" + root + "/delete-preview"),
                                                null,
                                                owner,
                                                null),
                                        200)
                                .get("scope_hash"))
                .isEqualTo(delete.get("scope_hash"));
        body(
                call(
                        "PATCH",
                        path("/nodes/" + root),
                        Map.of("content", "실제 변경", "expected_version", 2),
                        owner,
                        null),
                200);
        assertThat(
                        call(
                                        "DELETE",
                                        path(
                                                "/nodes/"
                                                        + root
                                                        + "?scope_hash="
                                                        + delete.get("scope_hash").asText()),
                                        null,
                                        owner,
                                        null)
                                .statusCode())
                .isEqualTo(409);
        delete =
                body(
                        call("GET", path("/nodes/" + root + "/delete-preview"), null, owner, null),
                        200);
        body(call("GET", path("/metrics"), null, owner, null), 200);
        assertThat(
                        call(
                                        "DELETE",
                                        path(
                                                "/nodes/"
                                                        + root
                                                        + "?scope_hash="
                                                        + delete.get("scope_hash").asText()),
                                        null,
                                        owner,
                                        null)
                                .statusCode())
                .isEqualTo(204);
    }

    @Test
    void supplementaryUnicodeSurvivesBackupAtTheApiLimit() throws Exception {
        String text = "😀".repeat(8000);
        body(
                call(
                        "POST",
                        path("/discussions"),
                        Map.of("id", UUID.randomUUID().toString(), "body", text),
                        owner,
                        null),
                201);
        assertThat(
                        call(
                                        "POST",
                                        path("/discussions"),
                                        Map.of(
                                                "id",
                                                UUID.randomUUID().toString(),
                                                "body",
                                                text + "😀"),
                                        owner,
                                        null)
                                .statusCode())
                .isEqualTo(422);
        body(call("PATCH", "/projects/" + pid, Map.of("name", "😀".repeat(60)), owner, null), 200);
        for (String format : List.of("json", "workspace")) {
            var exported = body(call("GET", path("/export/" + format), null, owner, null), 200);
            body(call("POST", "/projects/import/preview", exported.toString(), owner, null), 200);
            long imported =
                    body(
                                    call(
                                            "POST",
                                            "/projects/import",
                                            exported.toString(),
                                            owner,
                                            "unicode-" + format),
                                    201)
                            .get("project_id")
                            .asLong();
            var restored =
                    body(
                            call(
                                    "GET",
                                    "/projects/" + imported + "/export/" + format,
                                    null,
                                    owner,
                                    null),
                            200);
            var restoredGraph = format.equals("workspace") ? restored.get("graph") : restored;
            var exportedGraph = format.equals("workspace") ? exported.get("graph") : exported;
            assertThat(restoredGraph.get("project").get("name"))
                    .isEqualTo(exportedGraph.get("project").get("name"));
            if (format.equals("workspace"))
                assertThat(restored.get("discussions").get(0).get("body").asText()).isEqualTo(text);
        }
    }

    @Test
    void migratedPythonCommandsReplayWithoutDuplicateWritesOrRelaxingIdentity() throws Exception {
        long uid = jdbc.queryForObject("SELECT owner_id FROM project WHERE id=?", Long.class, pid);
        jdbc.update(
                "UPDATE project_user_role SET role='EDITOR' WHERE project_id=? AND user_id=?",
                pid,
                viewerId);
        JsonNode fixtures;
        try (var input = getClass().getResourceAsStream("/legacy-request-hashes.json")) {
            fixtures = json.readTree(input);
        }
        for (var fixture : fixtures) {
            var command = fixture.get("body");
            String id = command.get("id").asText(), kind = fixture.get("kind").asText();
            String table, endpoint, changedField;
            switch (kind) {
                case "task", "task_execution", "task_escape" -> {
                    jdbc.update("DELETE FROM work_item WHERE id=?", id);
                    table = "work_item";
                    endpoint = path("/tasks");
                    changedField = "title";
                }
                case "discussion" -> {
                    table = "discussion";
                    endpoint = path("/discussions");
                    changedField = "body";
                }
                case "reply" -> {
                    table = "discussion_reply";
                    endpoint = path("/discussions/" + id + "/replies");
                    changedField = "body";
                }
                case "proposal" -> {
                    table = "ai_proposal";
                    endpoint = path("/proposals?enqueue=true");
                    changedField = "instruction";
                    jdbc.update(
                            "INSERT INTO"
                                + " ai_proposal(id,project_id,actor_id,mode,instruction,sources,status,output,request_hash,created_at,updated_at)"
                                + " VALUES(?,?,?,'SUMMARY','','[]','SUCCEEDED','saved',?,now(),now())",
                            id,
                            pid,
                            uid,
                            fixture.get("hash").asText());
                }
                case "asset" -> {
                    table = "personal_asset";
                    endpoint = "/workspace/assets";
                    changedField = "name";
                }
                default -> throw new AssertionError(kind);
            }
            if (!kind.equals("proposal"))
                body(call("POST", endpoint, command.toString(), owner, null), 201);
            // These hashes are golden values from V3's Pydantic models and Python digest functions.
            jdbc.update(
                    "UPDATE " + table + " SET request_hash=? WHERE id=?",
                    fixture.get("hash").asText(),
                    id);
            if (table.equals("work_item"))
                jdbc.update(
                        "UPDATE work_item SET title='Edited after creation',version=1 WHERE id=?",
                        id);
            long events = jdbc.queryForObject("SELECT count(*) FROM outbox_event", Long.class);
            var replay = body(call("POST", endpoint, command.toString(), owner, null), 201);
            assertThat(replay.get("id").asText()).isEqualTo(id);
            if (table.equals("work_item"))
                assertThat(replay.get("title").asText()).isEqualTo("Edited after creation");
            assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_event", Long.class))
                    .isEqualTo(events);
            var changed = command.deepCopy();
            ((tools.jackson.databind.node.ObjectNode) changed).put(changedField, "다른 명령");
            assertThat(call("POST", endpoint, changed.toString(), owner, null).statusCode())
                    .isEqualTo(409);
            assertThat(call("POST", endpoint, command.toString(), viewer, null).statusCode())
                    .isEqualTo(409);
            assertThat(
                            jdbc.queryForObject(
                                    "SELECT count(*) FROM " + table + " WHERE id=?",
                                    Long.class,
                                    id))
                    .isEqualTo(1);
        }
    }

    @Test
    void concurrentTagDeletesAndVotesDoNotUpgradeSharedProjectLocks() throws Exception {
        for (boolean voting : List.of(false, true)) {
            var ids = new ArrayList<Long>();
            for (int index = 0; index < 8; index++) {
                long tag =
                        body(
                                        call(
                                                "POST",
                                                path("/tags"),
                                                Map.of("name", "tag-" + voting + index),
                                                owner,
                                                null),
                                        201)
                                .get("id")
                                .asLong();
                ids.add(tag);
                if (voting)
                    jdbc.update(
                            "INSERT INTO tag_summary(tag_id,summary_text,created_at)"
                                    + " VALUES(?,'summary',now())",
                            tag);
            }
            try (var gate =
                            java.sql.DriverManager.getConnection(
                                    DB.getJdbcUrl(), DB.getUsername(), DB.getPassword());
                    var pool = Executors.newVirtualThreadPerTaskExecutor()) {
                gate.setAutoCommit(false);
                try (var query =
                        gate.prepareStatement("SELECT id FROM project WHERE id=? FOR SHARE")) {
                    query.setLong(1, pid);
                    query.executeQuery().close();
                }
                var results = new ArrayList<Future<HttpResponse<String>>>();
                for (long tag : ids)
                    results.add(
                            pool.submit(
                                    () ->
                                            call(
                                                    voting ? "POST" : "DELETE",
                                                    path("/tags/" + tag + (voting ? "/vote" : "")),
                                                    null,
                                                    owner,
                                                    null)));
                try {
                    org.awaitility.Awaitility.await()
                            .atMost(java.time.Duration.ofSeconds(10))
                            .until(
                                    () ->
                                            jdbc.queryForObject(
                                                            "SELECT count(*) FROM pg_stat_activity"
                                                                + " WHERE"
                                                                + " datname=current_database() AND"
                                                                + " wait_event_type='Lock' AND"
                                                                + " query LIKE '%project%FOR"
                                                                + " UPDATE%'",
                                                            Integer.class)
                                                    >= 2);
                } finally {
                    gate.rollback();
                }
                for (var result : results) {
                    var response = result.get(15, TimeUnit.SECONDS);
                    assertThat(response.statusCode())
                            .as(response.body())
                            .isEqualTo(voting ? 200 : 204);
                }
            }
        }
    }

    @Test
    void claimRetentionPrunesOnlyClaimsExpiredOverOneDay() {
        jdbc.execute("TRUNCATE idempotency_request");
        long uid = jdbc.queryForObject("SELECT owner_id FROM project WHERE id=?", Long.class, pid);
        for (String age : List.of("2 days", "1 hour", "-1 day")) {
            jdbc.update(
                    "INSERT INTO"
                        + " idempotency_request(actor_id,project_id,idempotency_key,request_hash,created_at,expires_at)"
                        + " VALUES(?,?,?,?,now(),now()-?::interval)",
                    uid,
                    pid,
                    age,
                    "test-hash",
                    age);
        }
        claims.pruneExpired();
        assertThat(
                        jdbc.queryForList(
                                "SELECT idempotency_key FROM idempotency_request", String.class))
                .containsExactlyInAnyOrder("1 hour", "-1 day");
    }

    @Test
    void graphEtagChangesWhenTagMetadataChanges() throws Exception {
        var first = call("GET", path("/nodes"), null, owner, null);
        String initial = first.headers().firstValue("ETag").orElseThrow();
        var unchanged =
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + path("/nodes")))
                        .header("Authorization", "Bearer " + owner)
                        .header("If-None-Match", initial)
                        .GET()
                        .build();
        assertThat(http.send(unchanged, HttpResponse.BodyHandlers.ofString()).statusCode())
                .isEqualTo(304);
        var tag = body(call("POST", path("/tags"), Map.of("name", "old"), owner, null), 201);
        String created =
                call("GET", path("/nodes"), null, owner, null)
                        .headers()
                        .firstValue("ETag")
                        .orElseThrow();
        assertThat(created).isNotEqualTo(initial);
        body(
                call(
                        "PATCH",
                        path("/tags/" + tag.get("id").asLong()),
                        Map.of("name", "new"),
                        owner,
                        null),
                200);
        assertThat(
                        call("GET", path("/nodes"), null, owner, null)
                                .headers()
                                .firstValue("ETag")
                                .orElseThrow())
                .isNotEqualTo(created);
    }

    @Test
    void authorizationAndReplayHaveNoDuplicateEffects() throws Exception {
        String id = UUID.randomUUID().toString();
        var b = Map.of("id", id, "title", "한글 과제", "node_id", root);
        assertThat(call("POST", path("/tasks"), b, viewer, null).statusCode()).isEqualTo(403);
        body(call("POST", path("/tasks"), b, owner, null), 201);
        body(call("POST", path("/tasks"), b, owner, null), 201);
        assertThat(
                        call(
                                        "POST",
                                        path("/tasks"),
                                        Map.of("id", id, "title", "다른 요청"),
                                        owner,
                                        null)
                                .statusCode())
                .isEqualTo(409);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM work_item", Long.class)).isEqualTo(1);
        for (String suffix : List.of("/nodes/" + root, "/tags"))
            assertThat(
                            call(
                                            suffix.contains("nodes") ? "PATCH" : "POST",
                                            path(suffix),
                                            suffix.contains("nodes")
                                                    ? Map.of(
                                                            "content", "bad", "expected_version", 0)
                                                    : Map.of("name", "bad"),
                                            viewer,
                                            null)
                                    .statusCode())
                    .isEqualTo(403);
        assertThat(body(call("GET", path(""), null, viewer, null), 200).get("my_role").asText())
                .isEqualTo("VIEWER");
        String outsider = account("outsider@example.com");
        assertThat(call("GET", path("/tasks"), null, outsider, null).statusCode()).isEqualTo(403);
    }

    @Test
    void concurrentTaskUpdateHasOneWinnerAndBulkRollsBack() throws Exception {
        var a = task("a");
        var b = task("b");
        String path = path("/tasks/" + a.get("id").asText());
        var update = patch(a, "DOING");
        try (var pool = Executors.newVirtualThreadPerTaskExecutor()) {
            var results =
                    pool.invokeAll(
                            List.of(
                                    () -> call("PUT", path, update, owner, null).statusCode(),
                                    () -> call("PUT", path, update, owner, null).statusCode()));
            assertThat(List.of(results.get(0).get(), results.get(1).get()))
                    .containsExactlyInAnyOrder(200, 409);
        }
        var bulk =
                Map.of(
                        "status",
                        "DONE",
                        "tasks",
                        List.of(
                                Map.of("id", b.get("id").asText(), "expected_version", 0),
                                Map.of("id", a.get("id").asText(), "expected_version", 0)));
        assertThat(call("POST", path("/tasks/bulk-status"), bulk, owner, null).statusCode())
                .isEqualTo(409);
        assertThat(
                        jdbc.queryForObject(
                                "SELECT status FROM work_item WHERE id=?",
                                String.class,
                                b.get("id").asText()))
                .isEqualTo("TODO");
    }

    @Test
    void dependenciesAndChecklistRecurrencePreserveInvariants() throws Exception {
        var a = task("a");
        var b = task("b");
        String aid = a.get("id").asText(), bid = b.get("id").asText();
        b =
                body(
                        call(
                                "PUT",
                                path("/tasks/" + bid + "/dependencies"),
                                Map.of("expected_version", 0, "requires", List.of(aid)),
                                owner,
                                null),
                        200);
        assertThat(
                        call(
                                        "PUT",
                                        path("/tasks/" + aid + "/dependencies"),
                                        Map.of("expected_version", 0, "requires", List.of(bid)),
                                        owner,
                                        null)
                                .statusCode())
                .isEqualTo(422);
        assertThat(call("PUT", path("/tasks/" + bid), patch(b, "DONE"), owner, null).statusCode())
                .isEqualTo(409);
        var recurring = patch(a, "DONE");
        recurring.put(
                "checklist",
                List.of(Map.of("id", UUID.randomUUID().toString(), "text", "확인", "done", false)));
        recurring.put("repeat_every_days", 7);
        recurring.put("due_date", "2028-02-28");
        assertThat(call("PUT", path("/tasks/" + aid), recurring, owner, null).statusCode())
                .isEqualTo(409);
        recurring.put(
                "checklist",
                List.of(Map.of("id", UUID.randomUUID().toString(), "text", "확인", "done", true)));
        a = body(call("PUT", path("/tasks/" + aid), recurring, owner, null), 200);
        assertThat(
                        jdbc.queryForObject(
                                "SELECT due_date::text FROM work_item WHERE recurrence_parent_id=?",
                                String.class,
                                aid))
                .isEqualTo("2028-03-06");
        a = body(call("PUT", path("/tasks/" + aid), patch(a, "TODO"), owner, null), 200);
        body(call("PUT", path("/tasks/" + aid), patch(a, "DONE"), owner, null), 200);
        assertThat(
                        jdbc.queryForObject(
                                "SELECT count(*) FROM work_item WHERE recurrence_parent_id=?",
                                Long.class,
                                aid))
                .isEqualTo(1);
    }

    @Test
    void repliesNotificationsDraftsAndRevocationStayPrivate() throws Exception {
        String thread = UUID.randomUUID().toString();
        body(
                call("POST", path("/discussions"), Map.of("id", thread, "body", "논의"), owner, null),
                201);
        var reply =
                Map.of(
                        "id",
                        UUID.randomUUID().toString(),
                        "body",
                        "답글",
                        "mentions",
                        List.of(viewerId));
        body(call("POST", path("/discussions/" + thread + "/replies"), reply, owner, null), 201);
        body(call("POST", path("/discussions/" + thread + "/replies"), reply, owner, null), 201);
        var inbox = body(call("GET", "/workspace/inbox", null, viewer, null), 200);
        assertThat(inbox.get("items")).hasSize(1);
        assertThat(body(call("GET", "/workspace/inbox", null, owner, null), 200).get("items"))
                .isEmpty();
        var draft =
                Map.of(
                        "expected_version",
                        -1,
                        "item",
                        Map.of("id", UUID.randomUUID().toString(), "title", "초안"));
        body(call("PUT", path("/drafts/task"), draft, owner, null), 200);
        assertThat(call("PUT", path("/drafts/task"), draft, owner, null).statusCode())
                .isEqualTo(409);
        assertThat(
                        call("DELETE", path("/drafts/task?expected_version=0"), null, owner, null)
                                .statusCode())
                .isEqualTo(204);
        assertThat(call("PUT", path("/drafts/task"), draft, owner, null).statusCode())
                .isEqualTo(409);
        jdbc.update(
                "DELETE FROM project_user_role WHERE project_id=? AND user_id=?", pid, viewerId);
        assertThat(body(call("GET", "/workspace/inbox", null, viewer, null), 200).get("items"))
                .isEmpty();
    }

    @Test
    void workspaceBackupRoundTripRejectsBrokenReferencesAndReplaysOnce() throws Exception {
        var t = task("백업 과제");
        String thread = UUID.randomUUID().toString();
        body(
                call(
                        "POST",
                        path("/discussions"),
                        Map.of("id", thread, "body", "보존", "node_id", root),
                        owner,
                        null),
                201);
        body(
                call(
                        "POST",
                        path("/discussions/" + thread + "/replies"),
                        Map.of("id", UUID.randomUUID().toString(), "body", "답글"),
                        owner,
                        null),
                201);
        call("PUT", path("/bookmarks/" + root), null, owner, null);
        var exported = body(call("GET", path("/export/workspace"), null, owner, null), 200);
        var preview =
                body(
                        call("POST", "/projects/import/preview", exported.toString(), owner, null),
                        200);
        assertThat(preview.get("task_count").asInt()).isEqualTo(1);
        JsonNode restored;
        try (var pool = Executors.newVirtualThreadPerTaskExecutor()) {
            var results =
                    pool.<HttpResponse<String>>invokeAll(
                            List.of(
                                    () ->
                                            call(
                                                    "POST",
                                                    "/projects/import",
                                                    exported.toString(),
                                                    owner,
                                                    "same-backup"),
                                    () ->
                                            call(
                                                    "POST",
                                                    "/projects/import",
                                                    exported.toString(),
                                                    owner,
                                                    "same-backup")));
            restored = body(results.get(0).get(), 201);
            assertThat(body(results.get(1).get(), 201)).isEqualTo(restored);
        }
        long newPid = restored.get("project_id").asLong();
        assertThat(newPid).isNotEqualTo(pid);
        var again =
                body(
                        call("GET", "/projects/" + newPid + "/export/workspace", null, owner, null),
                        200);
        assertThat(again.get("tasks")).isEqualTo(exported.get("tasks"));
        assertThat(again.get("discussions")).isEqualTo(exported.get("discussions"));
        assertThat(again.get("replies")).isEqualTo(exported.get("replies"));
        var invalid = json.readTree(exported.toString());
        ((tools.jackson.databind.node.ObjectNode) invalid.get("tasks").get(0))
                .put("node_ref", "unknown");
        long count = jdbc.queryForObject("SELECT count(*) FROM project", Long.class);
        assertThat(
                        call("POST", "/projects/import", invalid.toString(), owner, "bad-backup")
                                .statusCode())
                .isEqualTo(422);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM project", Long.class))
                .isEqualTo(count);
    }

    @Test
    void nodePatchReplayAndDeleteRestoreKeepVersionsMonotonic() throws Exception {
        var patch = Map.of("content", "첫 변경", "expected_version", 0);
        body(call("PATCH", path("/nodes/" + root), patch, owner, "edit-once"), 200);
        body(call("PATCH", path("/nodes/" + root), patch, owner, "edit-once"), 200);
        assertThat(jdbc.queryForObject("SELECT version FROM node WHERE id=?", Integer.class, root))
                .isEqualTo(1);
        var operations = body(call("GET", path("/operations"), null, owner, null), 200);
        String id = operations.get("items").get(0).get("id").asText();
        var preview =
                body(call("GET", path("/operations/" + id + "/preview"), null, owner, null), 200);
        var undo = Map.of("preview_hash", preview.get("preview_hash").asText());
        body(call("POST", path("/operations/" + id + "/undo"), undo, owner, "undo-once"), 200);
        body(call("POST", path("/operations/" + id + "/undo"), undo, owner, "undo-once"), 200);
        assertThat(jdbc.queryForObject("SELECT version FROM node WHERE id=?", Integer.class, root))
                .isEqualTo(2);
        var child =
                body(
                                call(
                                        "POST",
                                        path("/nodes"),
                                        Map.of(
                                                "content",
                                                "legacy child",
                                                "parent_id",
                                                root,
                                                "depth",
                                                0),
                                        owner,
                                        null),
                                201)
                        .get(0);
        jdbc.update("UPDATE node SET depth=10 WHERE id=?", root);
        var delete =
                body(
                        call("GET", path("/nodes/" + root + "/delete-preview"), null, owner, null),
                        200);
        assertThat(
                        call(
                                        "DELETE",
                                        path(
                                                "/nodes/"
                                                        + root
                                                        + "?expected_version=2&scope_hash="
                                                        + delete.get("scope_hash").asText()),
                                        null,
                                        owner,
                                        "delete-once")
                                .statusCode())
                .isEqualTo(204);
        id =
                body(call("GET", path("/operations"), null, owner, null), 200)
                        .get("items")
                        .get(0)
                        .get("id")
                        .asText();
        preview = body(call("GET", path("/operations/" + id + "/preview"), null, owner, null), 200);
        body(
                call(
                        "POST",
                        path("/operations/" + id + "/undo"),
                        Map.of("preview_hash", preview.get("preview_hash").asText()),
                        owner,
                        "restore-once"),
                200);
        assertThat(jdbc.queryForObject("SELECT version FROM node WHERE id=?", Integer.class, root))
                .isEqualTo(3);
        assertThat(
                        jdbc.queryForObject(
                                "SELECT parent_id FROM node WHERE id=?",
                                Long.class,
                                child.get("id").asLong()))
                .isEqualTo(root);
    }

    @Test
    void durableQueueCancellationAndUncertainWorkDoNotRetry() throws Exception {
        var request =
                Map.of(
                        "id",
                        UUID.randomUUID().toString(),
                        "mode",
                        "SUMMARY",
                        "node_ids",
                        List.of(root));
        var p = body(call("POST", path("/proposals?enqueue=true"), request, owner, null), 201);
        String id = p.get("id").asText();
        assertThat(p.get("status").asText()).isEqualTo("QUEUED");
        body(call("POST", path("/proposals/" + id + "/cancel"), null, owner, null), 200);
        body(call("POST", path("/proposals?enqueue=true"), request, owner, null), 201);
        proposals.poll();
        assertThat(
                        jdbc.queryForObject(
                                "SELECT status FROM ai_proposal WHERE id=?", String.class, id))
                .isEqualTo("CANCELED");
        jdbc.update(
                "UPDATE ai_proposal SET status='RUNNING',updated_at=now()-interval '2"
                        + " minutes',lease_token='old' WHERE id=?",
                id);
        proposals.poll();
        assertThat(
                        jdbc.queryForObject(
                                "SELECT status FROM ai_proposal WHERE id=?", String.class, id))
                .isEqualTo("INTERRUPTED");
        body(
                call(
                        "PUT",
                        path("/proposals/policy"),
                        Map.of("expected_version", 0, "daily_limit", 0, "input_limit", 100),
                        owner,
                        null),
                200);
        assertThat(
                        call(
                                        "POST",
                                        path("/proposals?enqueue=true"),
                                        Map.of(
                                                "id",
                                                UUID.randomUUID().toString(),
                                                "mode",
                                                "ACTION",
                                                "node_ids",
                                                List.of(root)),
                                        owner,
                                        null)
                                .statusCode())
                .isEqualTo(429);
    }

    @Test
    void searchAndPersonalAssetsRespectDeletedProjectsAndOwnership() throws Exception {
        body(
                call(
                        "PATCH",
                        path("/nodes/" + root),
                        Map.of("content", "검색할 원문", "expected_version", 0),
                        owner,
                        null),
                200);
        assertThat(
                        body(
                                        call(
                                                "GET",
                                                "/workspace/knowledge?q="
                                                        + URLEncoder.encode(
                                                                "검색할", StandardCharsets.UTF_8),
                                                null,
                                                viewer,
                                                null),
                                        200)
                                .get("items"))
                .hasSize(1);
        String id = UUID.randomUUID().toString();
        body(
                call(
                        "POST",
                        "/workspace/assets",
                        Map.of("id", id, "kind", "TEMPLATE", "name", "내 템플릿", "project_id", pid),
                        owner,
                        null),
                201);
        assertThat(
                        call(
                                        "POST",
                                        "/workspace/assets/" + id + "/instantiate",
                                        null,
                                        viewer,
                                        "template")
                                .statusCode())
                .isEqualTo(404);
        body(
                call("POST", "/workspace/assets/" + id + "/instantiate", null, owner, "template"),
                201);
        call("DELETE", path(""), null, owner, null);
        assertThat(body(call("GET", "/workspace/knowledge", null, viewer, null), 200).get("items"))
                .isEmpty();
        assertThat(
                        call("POST", "/workspace/trash/" + pid + "/restore", null, viewer, null)
                                .statusCode())
                .isEqualTo(404);
        body(call("POST", "/workspace/trash/" + pid + "/restore", null, owner, null), 200);
    }
}
