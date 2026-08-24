package com.brainnet.spring;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

final class ApiModels {
    private ApiModels() {}

    record ProjectView(
            long id,
            String name,
            String description,
            long owner_id,
            OffsetDateTime created_at,
            OffsetDateTime updated_at,
            boolean is_deleted,
            Long member_count,
            long node_count,
            long tag_count) {}

    record NodeView(
            long id,
            long project_id,
            Long author_id,
            String content,
            String state,
            int depth,
            int order_index,
            Double pos_x,
            Double pos_y,
            Long parent_id,
            OffsetDateTime created_at,
            OffsetDateTime updated_at,
            List<Long> tags,
            int version) {}

    record NodePatch(
            Integer expected_version,
            String content,
            Double pos_x,
            Double pos_y,
            Integer depth,
            Integer order) {
        boolean hasChanges() {
            return content != null || pos_x != null || pos_y != null || depth != null || order != null;
        }
    }

    record NodeCreate(
            String content,
            String ai_prompt,
            Long parent_id,
            Integer depth,
            Integer order,
            Double pos_x,
            Double pos_y,
            String state) {}

    record ErrorView(String code, String message, String trace_id) {}

    record ValidationErrorView(
            String code,
            String message,
            String trace_id,
            List<Map<String, Object>> errors) {}
}
