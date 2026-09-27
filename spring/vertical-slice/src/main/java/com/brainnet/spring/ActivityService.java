package com.brainnet.spring;

import static com.brainnet.spring.VerticalService.timestamp;
import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Service
class ActivityService {
    record Activity(long id, Long user_id, Long project_id, String type, JsonNode payload, OffsetDateTime logged_at) {}
    static final Set<String> TYPES = Set.of("NODE_CREATE", "NODE_UPDATE", "NODE_DELETE", "NODE_RESTORE", "NODE_ACTIVATE", "NODE_DEACTIVATE",
            "PROJECT_CREATE", "PROJECT_UPDATE", "PROJECT_DELETE", "TAG_CREATE", "TAG_UPDATE", "TAG_DELETE", "TAG_APPLY", "TAG_REMOVE",
            "VOTE_CAST", "VOTE_CONFIRM", "INVITE_SENT", "INVITE_ACCEPT", "SUMMARY_CREATE", "MEMBER_REMOVE", "MEMBER_LEAVE", "MEMBER_ROLE_CHANGE");
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final ProjectAccessService access;
    ActivityService(JdbcTemplate jdbc, ObjectMapper mapper, ProjectAccessService access) {
        this.jdbc = jdbc; this.mapper = mapper; this.access = access;
    }

    // Caller owns the mutation transaction. Never include credentials, invitation tokens or full node contents.
    void append(long projectId, long userId, String type, Map<String, ?> payload) {
        if (!TYPES.contains(type)) throw new IllegalArgumentException("Unknown activity type");
        jdbc.update("INSERT INTO activity_log(user_id,project_id,type,payload,logged_at) VALUES (?,?,?::act_type_t,?::json,now())",
                userId, projectId, type, mapper.writeValueAsString(payload));
    }

    List<Activity> list(long projectId, long userId, Long before, int limit, String type) {
        access.member(projectId, userId);
        if (type != null && !TYPES.contains(type)) throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Unknown activity type");
        var args = new ArrayList<Object>();
        args.add(projectId);
        String filter = "";
        if (before != null) { filter += " AND id<?"; args.add(before); }
        if (type != null) { filter += " AND type::text=?"; args.add(type); }
        args.add(limit);
        return jdbc.query("SELECT * FROM activity_log WHERE project_id=?" + filter + " ORDER BY id DESC LIMIT ?",
                (rs, row) -> new Activity(rs.getLong("id"), (Long) rs.getObject("user_id"), (Long) rs.getObject("project_id"),
                        rs.getString("type"), rs.getString("payload") == null ? null : mapper.readTree(rs.getString("payload")),
                        timestamp(rs, "logged_at")), args.toArray());
    }
}
