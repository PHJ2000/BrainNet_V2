package com.brainnet.spring;

import static org.assertj.core.api.Assertions.*;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.nio.charset.StandardCharsets;
import java.sql.*;

@Testcontainers
class MigrationAdoptionIntegrationTest {
    @Container
    static final PostgreSQLContainer<?> DB = new PostgreSQLContainer<>("postgres:15-alpine");

    void adopt(String resource) throws Exception {
        try (var c =
                        DriverManager.getConnection(
                                DB.getJdbcUrl(), DB.getUsername(), DB.getPassword());
                var q = c.createStatement()) {
            q.execute("DROP SCHEMA public CASCADE;CREATE SCHEMA public");
            try (var input = getClass().getResourceAsStream(resource)) {
                q.execute(new String(input.readAllBytes(), StandardCharsets.UTF_8));
            }
            q.execute(
                    "INSERT INTO app_user(id,email,pw_hash,created_at)"
                        + " VALUES(900,'preserved@example.com','hash',now());INSERT INTO"
                        + " project(id,owner_id,name,is_deleted,created_at,updated_at)"
                        + " VALUES(900,900,'보존 프로젝트',false,now(),now());INSERT INTO"
                        + " project_user_role(project_id,user_id,role,invited_at)"
                        + " VALUES(900,900,'OWNER',now());INSERT INTO"
                        + " node(id,project_id,author_id,content,state,depth,order_index,version,created_at,updated_at)"
                        + " VALUES(900,900,900,'보존할 내용','ACTIVE',0,0,7,now(),now())");
            if (resource.contains("legacy-workspace"))
                q.execute(
                        "INSERT INTO"
                            + " work_item(id,project_id,creator_id,title,body,status,priority,version,request_hash,created_at,updated_at)"
                            + " VALUES('11111111-1111-4111-8111-111111111111',900,900,'기존"
                            + " 과제','','TODO','MEDIUM',3,'original',now(),now())");
        }
        String rawToken = "R".repeat(43);
        try (var connection =
                        DriverManager.getConnection(
                                DB.getJdbcUrl(), DB.getUsername(), DB.getPassword());
                var statement = connection.createStatement();
                var insert =
                        connection.prepareStatement(
                                "INSERT INTO invite_token(token,project_id,email,role,expires_at)"
                                    + " VALUES(?,900,'recipient@example.com','EDITOR',now()+interval"
                                    + " '1 day')")) {
            statement.execute(
                    "INSERT INTO app_user(id,email,pw_hash,created_at)"
                            + " VALUES(901,'recipient@example.com','hash',now())");
            insert.setString(
                    1,
                    resource.contains("legacy-workspace")
                            ? rawToken
                            : InvitationService.digest(rawToken));
            insert.executeUpdate();
        }
        var flyway =
                Flyway.configure()
                        .dataSource(DB.getJdbcUrl(), DB.getUsername(), DB.getPassword())
                        .baselineOnMigrate(true)
                        .baselineVersion("0")
                        .load();
        assertThat(flyway.migrate().success).isTrue();
        assertThat(flyway.migrate().migrationsExecuted).isZero();
        verifyInvitationAdoption(rawToken);

        try (var c =
                        DriverManager.getConnection(
                                DB.getJdbcUrl(), DB.getUsername(), DB.getPassword());
                var q = c.createStatement()) {
            try (var r = q.executeQuery("SELECT content,version FROM node WHERE id=900")) {
                assertThat(r.next()).isTrue();
                assertThat(r.getString(1)).isEqualTo("보존할 내용");
                assertThat(r.getInt(2)).isEqualTo(7);
            }
            try (var r = q.executeQuery("SELECT to_regclass('workspace_draft') IS NOT NULL")) {
                r.next();
                assertThat(r.getBoolean(1)).isTrue();
            }
            if (resource.contains("legacy-workspace"))
                try (var r = q.executeQuery("SELECT title,version FROM work_item")) {
                    r.next();
                    assertThat(r.getString(1)).isEqualTo("기존 과제");
                    assertThat(r.getInt(2)).isEqualTo(3);
                }
        }
    }

    void verifyInvitationAdoption(String rawToken) {
        var source =
                new org.springframework.jdbc.datasource.DriverManagerDataSource(
                        DB.getJdbcUrl(), DB.getUsername(), DB.getPassword());
        var jdbc = new org.springframework.jdbc.core.JdbcTemplate(source);
        var json = new tools.jackson.databind.json.JsonMapper();
        var access = new ProjectAccessService(jdbc);
        var outbox = new NodeOutboxService(jdbc, json);
        var activity = new ActivityService(jdbc, json, access, outbox);
        var projects =
                new ProjectService(
                        jdbc,
                        access,
                        activity,
                        org.mockito.Mockito.mock(NodeHistoryService.class),
                        outbox);
        var invitations =
                new InvitationService(
                        jdbc,
                        projects,
                        org.mockito.Mockito.mock(InviteMailService.class),
                        activity,
                        72);
        var transaction =
                new org.springframework.transaction.support.TransactionTemplate(
                        new org.springframework.jdbc.datasource.DataSourceTransactionManager(
                                source));
        String digest = InvitationService.digest(rawToken);
        assertThat(jdbc.queryForObject("SELECT token FROM invite_token", String.class))
                .isEqualTo(digest);
        assertThat(jdbc.queryForObject("SELECT token_hashed FROM invite_token", Boolean.class))
                .isTrue();
        assertThatThrownBy(() -> transaction.execute(status -> invitations.join(digest, 901)))
                .isInstanceOfSatisfying(
                        ApiExceptionHandler.ApiException.class,
                        error -> assertThat(error.code).isEqualTo("INVITE_NOT_FOUND"));
        assertThatThrownBy(() -> transaction.execute(status -> invitations.join(rawToken, 900)))
                .isInstanceOfSatisfying(
                        ApiExceptionHandler.ApiException.class,
                        error -> assertThat(error.code).isEqualTo("INVITE_RECIPIENT_MISMATCH"));
        jdbc.update("UPDATE invite_token SET expires_at=now()-interval '1 day'");
        assertThatThrownBy(() -> transaction.execute(status -> invitations.join(rawToken, 901)))
                .isInstanceOfSatisfying(
                        ApiExceptionHandler.ApiException.class,
                        error -> assertThat(error.code).isEqualTo("INVITE_EXPIRED"));
        jdbc.update("UPDATE invite_token SET expires_at=now()+interval '1 day'");
        var joined = transaction.execute(status -> invitations.join(rawToken, 901));
        assertThat(joined).containsEntry("status", "joined");
        assertThatThrownBy(() -> transaction.execute(status -> invitations.join(rawToken, 901)))
                .isInstanceOfSatisfying(
                        ApiExceptionHandler.ApiException.class,
                        error -> assertThat(error.code).isEqualTo("INVITE_ALREADY_USED"));
        assertThat(
                        jdbc.queryForObject(
                                "SELECT role::text FROM project_user_role WHERE project_id=900 AND"
                                        + " user_id=901",
                                String.class))
                .isEqualTo("EDITOR");
    }

    @Test
    void adoptsMainWithoutLosingExistingData() throws Exception {
        adopt("/db/migration-support/base.sql");
    }

    @Test
    void adoptsWorkspaceWithoutLosingTasksOrGraph() throws Exception {
        adopt("/legacy-workspace.sql");
    }
}
