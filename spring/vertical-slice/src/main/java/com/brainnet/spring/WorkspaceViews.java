package com.brainnet.spring;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import tools.jackson.databind.JsonNode;

import java.util.List;

/** Public response contracts. Database-only fields cannot escape through these records. */
final class WorkspaceViews {
    private WorkspaceViews() {}

    record Page<T, C>(List<T> items, C next_cursor) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Task(
            String id,
            long project_id,
            Long creator_id,
            String title,
            String body,
            String status,
            String priority,
            Long assignee_id,
            String due_date,
            Long node_id,
            List<TaskFields.ChecklistItem> checklist,
            Long repeat_every_days,
            String recurrence_parent_id,
            long version,
            String created_at,
            String updated_at) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    record PersonalTask(
            String id,
            long project_id,
            Long creator_id,
            String title,
            String body,
            String status,
            String priority,
            Long assignee_id,
            String due_date,
            Long node_id,
            List<TaskFields.ChecklistItem> checklist,
            Long repeat_every_days,
            String recurrence_parent_id,
            long version,
            String created_at,
            String updated_at,
            String project_name,
            String my_role,
            boolean blocked) {}

    record PersonalTasks(List<PersonalTask> items, String next_cursor, String today) {}

    record Counts(
            long total,
            long todo,
            long doing,
            long done,
            long canceled,
            long overdue,
            long due_today,
            long due_week,
            long blocked) {}

    record Workload(Long assignee_id, String email, long open, long overdue) {}

    record Overview(
            String today,
            Counts counts,
            List<Workload> workload,
            boolean workload_has_more,
            List<Task> upcoming) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Discussion(
            String id,
            long project_id,
            Long node_id,
            Long author_id,
            String body,
            boolean resolved,
            long version,
            String created_at,
            String updated_at) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Reply(
            String id,
            long project_id,
            String discussion_id,
            Long author_id,
            String body,
            List<Long> mentions,
            String created_at) {}

    record Notification(
            long id,
            long user_id,
            long project_id,
            String discussion_id,
            String reply_id,
            boolean read,
            String created_at,
            String project_name,
            String preview) {}

    record Link(long source_id, long target_id, String label, Long creator_id, String created_at) {}

    record LinkItem(
            long source_id,
            long target_id,
            String label,
            Long creator_id,
            String created_at,
            long node_id,
            String content,
            String direction) {}

    record Knowledge(
            long id,
            long project_id,
            String project_name,
            String content,
            long version,
            String state,
            boolean bookmarked) {}

    record Activity(
            long id,
            long project_id,
            Long actor_id,
            String kind,
            String target_id,
            String created_at) {}

    record TrashProject(long id, String name, String updated_at) {}

    record RestoredProject(long id, String name) {}

    record DraftPayload(JsonNode item, boolean attempted, long base_version, boolean resolved) {}

    record Draft(
            long user_id,
            long project_id,
            String kind,
            DraftPayload payload,
            long version,
            String updated_at) {}

    record Source(long id, long version, String content) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Proposal(
            String id,
            long project_id,
            Long actor_id,
            String mode,
            String instruction,
            List<Source> sources,
            String status,
            String output,
            String error_code,
            String task_id,
            String created_at,
            String updated_at,
            String started_at) {}

    record Policy(long daily_limit, long input_limit, long version, long used) {}

    record WorkerHealth(boolean enabled, boolean ready, boolean running, long failures) {}

    record EventHealth(String runtime, long pending) {}

    record Search(String q, Long project_id, boolean bookmarked) {}

    record Asset(String id, String name, String kind, String created_at, Search search) {}

    record ImportedProject(long project_id, String name) {}

    record Project(
            long id,
            String name,
            String description,
            long owner_id,
            java.time.OffsetDateTime created_at,
            java.time.OffsetDateTime updated_at,
            boolean is_deleted,
            Long member_count,
            Long node_count,
            Long tag_count,
            String my_role,
            boolean ai_enabled) {}

    record UndoResult(String operation_id, String undone_operation_id) {}

    record Operation(
            String id,
            long node_id,
            String kind,
            Long actor_id,
            String created_at,
            String expires_at,
            String undone_by,
            boolean expired,
            boolean can_undo,
            int node_count) {}

    record OperationPreview(
            String id,
            long node_id,
            String kind,
            Long actor_id,
            String created_at,
            String expires_at,
            String undone_by,
            boolean expired,
            boolean can_undo,
            int node_count,
            JsonNode before,
            JsonNode after,
            String preview_hash) {}

    record DeletePreview(
            List<JsonNode> nodes, int node_count, long expected_version, String scope_hash) {}

    record DepthAdjustment(String node_ref, int stored_depth, int depth) {}

    record StateCounts(long ACTIVE, long GHOST, long ARCHIVED) {}

    record BackupPreview(
            String name,
            String description,
            int node_count,
            int tag_count,
            int link_count,
            List<String> excluded,
            List<DepthAdjustment> depth_adjustments,
            StateCounts states,
            @com.fasterxml.jackson.annotation.JsonInclude(
                            com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
                    Integer schema_version,
            @com.fasterxml.jackson.annotation.JsonInclude(
                            com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
                    Integer task_count,
            @com.fasterxml.jackson.annotation.JsonInclude(
                            com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
                    Integer discussion_count,
            @com.fasterxml.jackson.annotation.JsonInclude(
                            com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
                    Integer proposal_count,
            @com.fasterxml.jackson.annotation.JsonInclude(
                            com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
                    Integer bookmark_count,
            @com.fasterxml.jackson.annotation.JsonInclude(
                            com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
                    Integer reply_count,
            @com.fasterxml.jackson.annotation.JsonInclude(
                            com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
                    Integer knowledge_link_count,
            @com.fasterxml.jackson.annotation.JsonInclude(
                            com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
                    Integer dependency_count) {}
}
