package db.migration;

import org.flywaydb.core.api.migration.BaseJavaMigration;
import org.flywaydb.core.api.migration.Context;
import org.springframework.core.io.ClassPathResource;

import java.sql.Connection;

/** Adopt either supported legacy schema without dropping user data. */
public class V1__Spring_owned_workspace extends BaseJavaMigration {
    @Override
    public boolean canExecuteInTransaction() {
        return false;
    } // PostgreSQL enum additions need a commit.

    private boolean exists(Connection c, String table) throws Exception {
        try (var q = c.prepareStatement("SELECT to_regclass(?) IS NOT NULL")) {
            q.setString(1, table);
            try (var r = q.executeQuery()) {
                r.next();
                return r.getBoolean(1);
            }
        }
    }

    private void script(Connection c, String name) throws Exception {
        try (var input =
                        new ClassPathResource("db/migration-support/" + name + ".sql")
                                .getInputStream();
                var statement = c.createStatement()) {
            // The PostgreSQL driver understands dollar-quoted DO blocks; a generic
            // semicolon splitter does not. Each resource is one atomic SQL batch.
            statement.execute(
                    new String(input.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
        }
    }

    private void adoptInvitations(Connection connection, boolean rawInvitations) throws Exception {
        // V1 is the unreleased adoption migration. The marker also makes partial retries safe:
        // new Spring invites use the default, while each legacy token is converted exactly once.
        try (var statement = connection.createStatement()) {
            statement.execute(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE"
                        + " table_schema=current_schema() AND table_name='invite_token' AND"
                        + " column_name='token_hashed') THEN ALTER TABLE invite_token ADD COLUMN"
                        + " token_hashed boolean NOT NULL DEFAULT true;"
                            + (rawInvitations ? " UPDATE invite_token SET token_hashed=false;" : "")
                            + " END IF; END $$");
        }
        try (var select = connection.createStatement();
                var rows =
                        select.executeQuery(
                                "SELECT token FROM invite_token WHERE token_hashed=false");
                var update =
                        connection.prepareStatement(
                                "UPDATE invite_token SET token=?,token_hashed=true WHERE token=?"
                                        + " AND token_hashed=false")) {
            while (rows.next()) {
                String raw = rows.getString(1);
                String hash =
                        java.util.Base64.getUrlEncoder()
                                .withoutPadding()
                                .encodeToString(
                                        java.security.MessageDigest.getInstance("SHA-256")
                                                .digest(
                                                        raw.getBytes(
                                                                java.nio.charset.StandardCharsets
                                                                        .UTF_8)));
                update.setString(1, hash);
                update.setString(2, raw);
                update.executeUpdate();
            }
        }
    }

    @Override
    public void migrate(Context context) throws Exception {
        var c = context.getConnection();
        boolean rawInvitations = false;
        if (!exists(c, "app_user")) script(c, "base");
        else {
            try (var q = c.createStatement();
                    var r = q.executeQuery("SELECT version_num FROM alembic_version")) {
                if (!r.next()
                        || !java.util.Set.of(
                                        "c2f4a6b8d010",
                                        "9e1c2a7d4b10",
                                        "b810001",
                                        "b811001",
                                        "b822001",
                                        "b922001",
                                        "b922002",
                                        "b922003",
                                        "b922004")
                                .contains(r.getString(1)))
                    throw new IllegalStateException(
                            "Unsupported legacy schema: upgrade it before Spring adoption");
                rawInvitations = !"c2f4a6b8d010".equals(r.getString(1));
            }
            // Idempotent enum/index expansion preserves both main and Workspace schemas.
            script(c, "main-operations");
        }
        adoptInvitations(c, rawInvitations);
        if (!exists(c, "node_operation")) script(c, "b810001");
        if (!exists(c, "project_import")) script(c, "b811001");
        script(c, "b822001");
        if (!exists(c, "work_item")) script(c, "b922001");
        if (!exists(c, "personal_asset")) script(c, "b922002");
        if (!exists(c, "workspace_draft")) script(c, "b922003");
        try (var q = c.createStatement();
                var r =
                        q.executeQuery(
                                "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE"
                                    + " table_schema=current_schema() AND table_name='work_item'"
                                    + " AND column_name='checklist')")) {
            r.next();
            if (!r.getBoolean(1)) script(c, "b922004");
        }
    }
}
