package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.VerticalService.timestamp;
import jakarta.validation.constraints.NotNull;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class MemberService {
    enum Role { OWNER, EDITOR }
    record ChangeRole(@NotNull Role role) {}
    record Member(long user_id, String name, String email, String role, OffsetDateTime invited_at, OffsetDateTime accepted_at) {}
    private static final String SELECT = "SELECT m.*,u.name,u.email FROM project_user_role m JOIN app_user u ON u.id=m.user_id ";
    private final JdbcTemplate jdbc;
    private final ProjectService projects;
    private final ProjectAccessService access;
    private final ActivityService activity;
    private final NodeOutboxService outbox;
    MemberService(JdbcTemplate jdbc, ProjectService projects, ProjectAccessService access, ActivityService activity, NodeOutboxService outbox) {
        this.jdbc = jdbc; this.projects = projects; this.access = access; this.activity = activity; this.outbox = outbox;
    }

    private Member view(java.sql.ResultSet rs, int row) throws java.sql.SQLException {
        return new Member(rs.getLong("user_id"), rs.getString("name"), rs.getString("email"), rs.getString("role"),
                timestamp(rs, "invited_at"), timestamp(rs, "accepted_at"));
    }

    List<Member> list(long projectId, long userId, long after, int limit) {
        access.member(projectId, userId);
        return jdbc.query(SELECT + "WHERE m.project_id=? AND m.user_id>? ORDER BY m.user_id LIMIT ?", this::view, projectId, after, limit);
    }

    private Member member(long projectId, long userId) {
        var members = jdbc.query(SELECT + "WHERE m.project_id=? AND m.user_id=?", this::view, projectId, userId);
        if (members.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "MEMBER_NOT_FOUND", "Project member not found");
        return members.getFirst();
    }

    @Transactional
    public Member changeRole(long projectId, long targetId, Role role, long actor) {
        projects.lockActive(projectId);
        access.owner(projectId, actor);
        var target = member(projectId, targetId);
        if (target.role().equals(role.name())) return target;
        if (role == Role.EDITOR) throw transferRequired();
        // With the existing OWNER/EDITOR roles, promotion transfers sole ownership.
        jdbc.update("UPDATE project_user_role SET role='EDITOR' WHERE project_id=? AND role='OWNER'", projectId);
        jdbc.update("UPDATE project_user_role SET role='OWNER' WHERE project_id=? AND user_id=?", projectId, targetId);
        jdbc.update("UPDATE project SET owner_id=?,updated_at=now() WHERE id=?", targetId, projectId);
        activity.append(projectId, actor, "MEMBER_ROLE_CHANGE", Map.of("previous_owner_id", actor, "owner_id", targetId));
        outbox.append(projectId, projectId, "membership.changed", Map.of("user_id", targetId, "action", "ownership_transferred"));
        return member(projectId, targetId);
    }

    @Transactional
    public void remove(long projectId, long targetId, long actor, boolean leaving) {
        projects.lockActive(projectId);
        if (leaving) access.member(projectId, actor); else access.owner(projectId, actor);
        var target = member(projectId, targetId);
        if (target.role().equals("OWNER")) throw transferRequired();
        jdbc.update("DELETE FROM project_user_role WHERE project_id=? AND user_id=?", projectId, targetId);
        jdbc.update("DELETE FROM invite_token WHERE project_id=? AND email=?", projectId, target.email());
        int votes = jdbc.update("DELETE FROM vote v USING tag_summary s,tag t "
                + "WHERE v.tag_summary_id=s.id AND s.tag_id=t.id AND t.project_id=? AND v.voter_id=?", projectId, targetId);
        activity.append(projectId, actor, leaving ? "MEMBER_LEAVE" : "MEMBER_REMOVE", Map.of("user_id", targetId, "removed_votes", votes));
        outbox.append(projectId, projectId, "membership.changed", Map.of("user_id", targetId, "action", leaving ? "left" : "removed"));
    }

    private ApiException transferRequired() {
        return new ApiException(HttpStatus.CONFLICT, "OWNERSHIP_TRANSFER_REQUIRED", "Transfer ownership to another member first");
    }
}
