package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;

@Service
class ProjectAccessService {
    private final JdbcTemplate jdbc;
    ProjectAccessService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    void active(long projectId) {
        // Shared locks keep ordinary writes concurrent, but serialize them with revocation/deletion.
        String lock = TransactionSynchronizationManager.isActualTransactionActive() ? " FOR SHARE" : "";
        if (jdbc.queryForList("SELECT id FROM project WHERE id=? AND is_deleted=false" + lock, Long.class, projectId).isEmpty()) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Project not found");
        }
    }

    void member(long projectId, long userId) {
        active(projectId);
        if (jdbc.queryForObject("SELECT count(*) FROM project_user_role WHERE project_id=? AND user_id=?", Long.class, projectId, userId) == 0) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "Not a project member");
        }
    }

    void owner(long projectId, long userId) {
        active(projectId);
        if (jdbc.queryForObject("SELECT count(*) FROM project_user_role m JOIN project p ON p.id=m.project_id "
                + "WHERE m.project_id=? AND m.user_id=? AND m.role='OWNER' AND p.owner_id=m.user_id", Long.class, projectId, userId) == 0) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "Owner permission required");
        }
    }
}
