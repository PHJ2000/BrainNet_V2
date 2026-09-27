package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.VerticalService.timestamp;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.OffsetDateTime;
import java.util.Base64;
import java.util.Locale;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class InvitationService {
    record Invitation(String invite_token, long project_id, String email, OffsetDateTime expires_at, String delivery) {}
    private final JdbcTemplate jdbc;
    private final ProjectService projects;
    private final InviteMailService mail;
    private final ActivityService activity;
    private final long expiryHours;
    private final SecureRandom random = new SecureRandom();

    InvitationService(JdbcTemplate jdbc, ProjectService projects, InviteMailService mail, ActivityService activity,
                      @Value("${INVITE_EXPIRY_HOURS:72}") long expiryHours) {
        this.jdbc = jdbc; this.projects = projects; this.mail = mail; this.expiryHours = expiryHours;
        this.activity = activity;
        if (expiryHours < 1 || expiryHours > 720) throw new IllegalStateException("INVITE_EXPIRY_HOURS must be between 1 and 720");
    }

    @Transactional
    public Invitation invite(long projectId, String email, long userId) {
        projects.lockActive(projectId);
        projects.requireOwner(projectId, userId);
        // Match registration: preserve the local part; normalize only the email domain.
        int at = email.lastIndexOf('@');
        email = email.substring(0, at + 1) + email.substring(at + 1).toLowerCase(Locale.ROOT);
        if (jdbc.queryForObject("SELECT count(*) FROM project_user_role m JOIN app_user u ON u.id=m.user_id "
                + "WHERE m.project_id=? AND u.email=?", Long.class, projectId, email) > 0) {
            throw new ApiException(HttpStatus.CONFLICT, "ALREADY_PROJECT_MEMBER", "Recipient is already a project member");
        }
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        OffsetDateTime expires = jdbc.queryForObject("INSERT INTO invite_token(token,project_id,email,role,expires_at,accepted_at) "
                + "VALUES (?,?,?,'EDITOR',now() + (? * interval '1 hour'),null) "
                + "ON CONFLICT (email,project_id) DO UPDATE SET token=excluded.token,role='EDITOR',"
                + "expires_at=excluded.expires_at,accepted_at=null RETURNING expires_at",
                (rs, row) -> timestamp(rs, "expires_at"), digest(token), projectId, email, expiryHours);
        // A failed SMTP submission rolls back both a new invitation and a replacement token.
        mail.send(email, projectId, token, expires);
        activity.append(projectId, userId, "INVITE_SENT", Map.of("expires_at", expires.toString()));
        return new Invitation(token, projectId, email, expires, "smtp");
    }

    @Transactional
    public Map<String, Object> join(String token, long userId) {
        String digest = digest(token);
        var ids = jdbc.queryForList("SELECT project_id FROM invite_token WHERE token=?", Long.class, digest);
        if (ids.isEmpty()) throw invalid();
        long projectId = ids.getFirst();
        // Same order as issuance/deletion: project first, invitation second.
        projects.lockActive(projectId);
        record Pending(String email, boolean expired, boolean accepted) {}
        var invites = jdbc.query("SELECT email,expires_at <= clock_timestamp() AS expired,accepted_at IS NOT NULL AS accepted "
                + "FROM invite_token WHERE token=? AND project_id=? FOR UPDATE",
                (rs, row) -> new Pending(rs.getString("email"), rs.getBoolean("expired"), rs.getBoolean("accepted")), digest, projectId);
        if (invites.isEmpty()) throw invalid();
        var invite = invites.getFirst();
        String email = jdbc.queryForObject("SELECT email FROM app_user WHERE id=?", String.class, userId);
        if (!invite.email().equals(email)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "INVITE_RECIPIENT_MISMATCH", "Invitation belongs to another account");
        }
        if (invite.accepted()) throw new ApiException(HttpStatus.CONFLICT, "INVITE_ALREADY_USED", "Invitation has already been used");
        if (invite.expired()) throw new ApiException(HttpStatus.GONE, "INVITE_EXPIRED", "Invitation has expired");
        jdbc.update("INSERT INTO project_user_role(project_id,user_id,role,invited_at,accepted_at) "
                + "VALUES (?,?,'EDITOR',now(),now()) ON CONFLICT (project_id,user_id) DO NOTHING", projectId, userId);
        jdbc.update("UPDATE invite_token SET accepted_at=now() WHERE token=?", digest);
        activity.append(projectId, userId, "INVITE_ACCEPT", Map.of());
        return Map.of("project_id", projectId, "status", "joined");
    }

    static String digest(String token) {
        try {
            return Base64.getUrlEncoder().withoutPadding().encodeToString(
                    MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }

    private ApiException invalid() {
        return new ApiException(HttpStatus.NOT_FOUND, "INVITE_NOT_FOUND", "Invitation not found");
    }
}
