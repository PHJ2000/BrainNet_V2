package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.VerticalService.timestamp;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class VoteService {
    record Vote(long id, long tag_summary_id, Long voter_id, OffsetDateTime created_at) {}
    record History(long id, long project_id, Long tag_summary_id, OffsetDateTime decided_at) {}
    private final JdbcTemplate jdbc;
    private final VerticalService nodes;
    private final ProjectService projects;
    private final NodeOutboxService outbox;
    VoteService(JdbcTemplate jdbc, VerticalService nodes, ProjectService projects, NodeOutboxService outbox) {
        this.jdbc = jdbc; this.nodes = nodes; this.projects = projects; this.outbox = outbox;
    }

    private History historyView(ResultSet rs, int row) throws SQLException {
        return new History(rs.getLong("id"), rs.getLong("project_id"), (Long) rs.getObject("tag_summary_id"), timestamp(rs, "decided_at"));
    }

    @Transactional
    public Vote cast(long projectId, long tagId, long userId) {
        nodes.requireMember(projectId, userId);
        var summaries = jdbc.queryForList("SELECT s.id FROM tag_summary s JOIN tag t ON t.id=s.tag_id "
                + "WHERE t.project_id=? AND t.id=? ORDER BY s.id DESC LIMIT 1 FOR UPDATE OF s", Long.class, projectId, tagId);
        if (summaries.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Tag summary not found");
        long summary = summaries.getFirst();
        if (jdbc.queryForObject("SELECT count(*) FROM vote WHERE tag_summary_id=? AND voter_id=?", Long.class, summary, userId) > 0) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "이미 투표했습니다.");
        }
        Vote vote = jdbc.queryForObject("INSERT INTO vote(tag_summary_id,voter_id,created_at) VALUES (?,?,now()) RETURNING *",
                (rs, row) -> new Vote(rs.getLong("id"), rs.getLong("tag_summary_id"), rs.getLong("voter_id"), timestamp(rs, "created_at")), summary, userId);
        outbox.append(projectId, vote.id(), "vote:cast", Map.of("id", vote.id(), "tag_summary_id", summary,
                "voter_id", userId, "created_at", vote.created_at().toString()));
        return vote;
    }

    @Transactional
    public History confirm(long projectId, Long winningTagId, long userId) {
        projects.requireOwner(projectId, userId);
        var summaries = jdbc.queryForList("SELECT s.id FROM tag_summary s JOIN tag t ON t.id=s.tag_id "
                + "WHERE t.project_id=? ORDER BY s.id FOR UPDATE OF s", Long.class, projectId);
        if (summaries.isEmpty()) throw noVotes();
        String placeholders = String.join(",", java.util.Collections.nCopies(summaries.size(), "?"));
        var winners = jdbc.queryForList("SELECT tag_summary_id FROM vote WHERE tag_summary_id IN (" + placeholders
                + ") GROUP BY tag_summary_id ORDER BY count(*) DESC,min(id) LIMIT 1", Long.class, summaries.toArray());
        if (winners.isEmpty()) throw noVotes();
        long chosen = winners.getFirst();
        if (winningTagId != null) {
            var selected = jdbc.queryForList("SELECT s.id FROM tag_summary s JOIN tag t ON t.id=s.tag_id "
                    + "WHERE t.project_id=? AND t.id=? ORDER BY s.id DESC LIMIT 1", Long.class, projectId, winningTagId);
            if (selected.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "유효한 태그 요약이 아닙니다.");
            chosen = selected.getFirst();
        }
        History history = jdbc.queryForObject("INSERT INTO project_history(project_id,tag_summary_id,decided_at) "
                + "VALUES (?,?,now()) RETURNING *", this::historyView, projectId, chosen);
        jdbc.update("DELETE FROM vote WHERE tag_summary_id IN (" + placeholders + ")", summaries.toArray());
        outbox.append(projectId, history.id(), "vote:confirmed", Map.of("id", history.id(), "tag_summary_id", chosen,
                "decided_at", history.decided_at().toString()));
        return history;
    }

    private ApiException noVotes() { return new ApiException(HttpStatus.CONFLICT, "CONFLICT", "진행 중인 투표가 없습니다."); }

    List<History> history(long projectId, long userId) {
        nodes.requireMember(projectId, userId);
        return jdbc.query("SELECT * FROM project_history WHERE project_id=? ORDER BY id", this::historyView, projectId);
    }

    History entry(long projectId, long entryId, long userId) {
        nodes.requireMember(projectId, userId);
        var entries = jdbc.query("SELECT * FROM project_history WHERE project_id=? AND id=?", this::historyView, projectId, entryId);
        if (entries.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "History entry not found");
        return entries.getFirst();
    }
}
