package com.brainnet.spring;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Positive;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/projects/{projectId}")
class ProjectOperationsController {
    record Restore(@Min(0) Integer expected_version) {}
    private final NodeHistoryService history;
    private final VerticalService nodes;
    private final ActivityService activity;
    private final NodeMetricsService metrics;
    private final MemberService members;
    ProjectOperationsController(NodeHistoryService history, VerticalService nodes, ActivityService activity,
                                NodeMetricsService metrics, MemberService members) {
        this.history = history; this.nodes = nodes; this.activity = activity; this.metrics = metrics; this.members = members;
    }

    @GetMapping("/nodes/{nodeId}/versions")
    List<NodeHistoryService.Version> versions(@PathVariable long projectId, @PathVariable long nodeId,
            @RequestParam(required = false) @Min(0) Integer before_version, @RequestParam(defaultValue = "50") @Min(1) @Max(100) int limit,
            @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        return history.list(projectId, nodeId, actor, before_version, limit);
    }

    @GetMapping("/nodes/{nodeId}/versions/{version}")
    NodeHistoryService.Version version(@PathVariable long projectId, @PathVariable long nodeId, @PathVariable @Min(0) int version,
                                      @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        return history.get(projectId, nodeId, version, actor);
    }

    @PostMapping("/nodes/{nodeId}/versions/{version}/restore")
    ApiModels.NodeView restore(@PathVariable long projectId, @PathVariable long nodeId, @PathVariable @Min(0) int version,
                              @Valid @RequestBody Restore body, @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        return nodes.restoreNode(projectId, nodeId, version, body.expected_version(), actor);
    }

    @GetMapping("/activities")
    List<ActivityService.Activity> activities(@PathVariable long projectId,
            @RequestParam(required = false) @Positive Long before_id, @RequestParam(defaultValue = "50") @Min(1) @Max(100) int limit,
            @RequestParam(required = false) String type, @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        return activity.list(projectId, actor, before_id, limit, type);
    }

    @GetMapping("/nodes/{nodeId}/metrics")
    NodeMetricsService.Metrics metric(@PathVariable long projectId, @PathVariable long nodeId,
                                     @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        return metrics.refresh(projectId, nodeId, actor).getFirst();
    }

    @GetMapping("/metrics")
    List<NodeMetricsService.Metrics> metrics(@PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        return metrics.refresh(projectId, null, actor);
    }

    @GetMapping("/members")
    List<MemberService.Member> members(@PathVariable long projectId,
            @RequestParam(defaultValue = "0") @Min(0) long after_user_id, @RequestParam(defaultValue = "100") @Min(1) @Max(100) int limit,
            @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        return members.list(projectId, actor, after_user_id, limit);
    }

    @PatchMapping("/members/{userId}")
    MemberService.Member changeRole(@PathVariable long projectId, @PathVariable long userId,
            @Valid @RequestBody MemberService.ChangeRole body, @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        return members.changeRole(projectId, userId, body.role(), actor);
    }

    @DeleteMapping("/members/{userId}")
    ResponseEntity<Void> remove(@PathVariable long projectId, @PathVariable long userId, @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        members.remove(projectId, userId, actor, false);
        return ResponseEntity.noContent().build();
    }

    @DeleteMapping("/members/me")
    ResponseEntity<Void> leave(@PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long actor) {
        members.remove(projectId, actor, actor, true);
        return ResponseEntity.noContent().build();
    }
}
