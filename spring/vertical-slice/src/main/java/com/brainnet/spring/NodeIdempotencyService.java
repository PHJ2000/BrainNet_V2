package com.brainnet.spring;

import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
class NodeIdempotencyService {
    record Claim(long id, String responseBody) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final long leaseSeconds;

    NodeIdempotencyService(JdbcTemplate jdbc, PlatformTransactionManager manager,
                           @Value("${OPENAI_TIMEOUT_SECONDS:30}") long timeoutSeconds) {
        this.jdbc = jdbc;
        this.transaction = new TransactionTemplate(manager);
        this.leaseSeconds = Math.max(120, timeoutSeconds + 60);
    }

    Claim claim(long projectId, long userId, String key, ApiModels.NodeCreate body) {
        if (key == null) return null;
        if (key.isBlank() || key.length() > 128) {
            throw new ApiExceptionHandler.ApiException(HttpStatus.UNPROCESSABLE_ENTITY,
                    "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must contain 1 to 128 characters");
        }
        String hash = NodeRequestFingerprint.hash(body);
        return transaction.execute(status -> {
            List<Long> inserted = jdbc.query("""
                    INSERT INTO idempotency_request
                        (actor_id,project_id,idempotency_key,request_hash,created_at,expires_at)
                    VALUES (?,?,?,?,now(),now()+? * interval '1 second')
                    ON CONFLICT (actor_id,idempotency_key) DO UPDATE SET
                        id=EXCLUDED.id,project_id=EXCLUDED.project_id,request_hash=EXCLUDED.request_hash,
                        response_status=NULL,response_body=NULL,created_at=now(),expires_at=EXCLUDED.expires_at
                    WHERE idempotency_request.expires_at <= now()
                    RETURNING id
                    """, (rs, row) -> rs.getLong("id"), userId, projectId, key, hash, leaseSeconds);
            if (!inserted.isEmpty()) return new Claim(inserted.getFirst(), null);
            var rows = jdbc.queryForList("""
                    SELECT id,project_id,request_hash,response_status,response_body::text AS response_body
                    FROM idempotency_request WHERE actor_id=? AND idempotency_key=?
                    """, userId, key);
            if (rows.isEmpty()) throw inProgress();
            var row = rows.getFirst();
            if (((Number) row.get("project_id")).longValue() != projectId || !hash.equals(row.get("request_hash"))) {
                throw new ApiExceptionHandler.ApiException(HttpStatus.CONFLICT, "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency-Key was already used with a different request");
            }
            if (row.get("response_status") == null || row.get("response_body") == null) throw inProgress();
            return new Claim(((Number) row.get("id")).longValue(), (String) row.get("response_body"));
        });
    }

    // Called inside the node transaction. The lock also fences expired owners.
    void lock(Claim claim) {
        if (claim == null) return;
        var rows = jdbc.queryForList("""
                SELECT id FROM idempotency_request
                WHERE id=? AND response_status IS NULL AND expires_at > now() FOR UPDATE
                """, claim.id());
        if (rows.isEmpty()) throw inProgress();
    }

    String complete(Claim claim, String response) {
        if (claim == null) return response;
        jdbc.update("""
                UPDATE idempotency_request SET response_status=201,response_body=?::jsonb,
                    expires_at=now()+interval '24 hours' WHERE id=?
                """, response, claim.id());
        return jdbc.queryForObject("SELECT response_body::text FROM idempotency_request WHERE id=?",
                String.class, claim.id());
    }

    void release(Claim claim) {
        if (claim == null) return;
        transaction.executeWithoutResult(status -> jdbc.update(
                "DELETE FROM idempotency_request WHERE id=? AND response_status IS NULL", claim.id()));
    }

    private static ApiExceptionHandler.ApiException inProgress() {
        return new ApiExceptionHandler.ApiException(HttpStatus.CONFLICT, "IDEMPOTENCY_IN_PROGRESS",
                "Idempotency request is in progress");
    }
}
