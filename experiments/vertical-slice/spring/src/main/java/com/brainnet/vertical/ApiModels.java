package com.brainnet.vertical;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

final class ApiModels {
    private ApiModels() {}

    record ProjectCreate(@NotBlank @Size(max = 120) String name, @Size(max = 2000) String description) {}
    record ProjectView(long id, long owner_id, String name, String description) {}
    record NodeCreate(@NotBlank @Size(max = 2000) String content, Long parent_id,
                      @Min(0) Integer depth, Integer order, Double pos_x, Double pos_y) {
        int depthValue() { return depth == null ? 0 : depth; }
        int orderValue() { return order == null ? 0 : order; }
        double posXValue() { return pos_x == null ? 0.0 : pos_x; }
        double posYValue() { return pos_y == null ? 0.0 : pos_y; }
    }
    record NodePatch(@NotNull @Min(0) Integer expected_version, @NotBlank @Size(max = 2000) String content,
                     Double pos_x, Double pos_y) {}
    record NodeView(long id, long project_id, Long author_id, String content, String state,
                    Double pos_x, Double pos_y, int depth, int order_index, Long parent_id, int version) {}
    record ResetView(long project_id, Long first_node_id, int nodes, boolean root) {}
    record StateView(long roots, long nodes, int max_version, long projects, long memberships) {}
    record ErrorView(String code, String message, String trace_id) {}
}
