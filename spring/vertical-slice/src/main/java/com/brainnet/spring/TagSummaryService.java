package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.VerticalService.timestamp;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class TagSummaryService {
    record Summary(long id, long tag_id, String summary_text, OffsetDateTime created_at) {}
    private final JdbcTemplate jdbc;
    private final ProjectService projects;
    private final TagService tags;

    TagSummaryService(JdbcTemplate jdbc, ProjectService projects, TagService tags) {
        this.jdbc = jdbc; this.projects = projects; this.tags = tags;
    }

    private Summary view(ResultSet rs, int row) throws SQLException {
        return new Summary(rs.getLong("id"), rs.getLong("tag_id"), rs.getString("summary_text"), timestamp(rs, "created_at"));
    }

    List<Summary> list(long projectId, long tagId, long userId) {
        tags.get(projectId, tagId, userId);
        return jdbc.query("SELECT * FROM tag_summary WHERE tag_id=? ORDER BY id DESC", this::view, tagId);
    }

    Summary latest(long projectId, long tagId, long userId) {
        tags.get(projectId, tagId, userId);
        var summaries = jdbc.query("SELECT * FROM tag_summary WHERE tag_id=? ORDER BY id DESC LIMIT 1", this::view, tagId);
        if (summaries.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Tag summary not found");
        return summaries.getFirst();
    }

    @Transactional
    public Summary generate(long projectId, long tagId, long userId) {
        projects.lockActive(projectId);
        projects.requireOwner(projectId, userId);
        var tag = tags.get(projectId, tagId, userId);
        // All summaries remain immutable once the first vote in this project has been cast.
        if (jdbc.queryForObject("SELECT count(*) FROM vote v JOIN tag_summary s ON s.id=v.tag_summary_id "
                + "JOIN tag t ON t.id=s.tag_id WHERE t.project_id=?", Long.class, projectId) > 0) {
            throw new ApiException(HttpStatus.CONFLICT, "VOTING_IN_PROGRESS", "Confirm the current vote before generating summaries");
        }
        // Deterministic local extractive summary: one snapshot query, no external provider or paid calls.
        var ideas = jdbc.queryForList("SELECT left(regexp_replace(n.content, '\\s+', ' ', 'g'),240) AS excerpt "
                + "FROM node n JOIN tag_node tn ON tn.node_id=n.id WHERE tn.tag_id=? AND n.project_id=? "
                + "AND n.state='ACTIVE' AND btrim(n.content) NOT IN ('','?','주제를 입력하세요') "
                + "ORDER BY n.depth,n.order_index,n.id LIMIT 51", String.class, tagId, projectId);
        if (ideas.isEmpty()) throw new ApiException(HttpStatus.CONFLICT, "NO_SUMMARIZABLE_NODES", "Tag has no active ideas to summarize");
        String text = tag.name() + "\n" + String.join("\n", ideas.stream().limit(50).map(s -> "- " + s.strip()).toList());
        if (ideas.size() > 50) text += "\n(처음 50개 아이디어 발췌)";
        // Repeated generation with unchanged content reuses the same snapshot.
        var current = jdbc.query("SELECT * FROM tag_summary WHERE tag_id=? ORDER BY id DESC LIMIT 1", this::view, tagId);
        if (!current.isEmpty() && current.getFirst().summary_text().equals(text)) return current.getFirst();
        return jdbc.queryForObject("INSERT INTO tag_summary(tag_id,summary_text,created_at) VALUES (?,?,now()) RETURNING *",
                this::view, tagId, text);
    }
}
