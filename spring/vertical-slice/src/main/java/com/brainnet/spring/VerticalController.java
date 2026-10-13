package com.brainnet.spring;

import static com.brainnet.spring.ApiModels.*;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
class VerticalController {
    private final VerticalService service;
    private final NodeCreationAdmission admission;
    private final NodeOperationService operations;
    private final ProjectPresentation presentation;
    private final NodeCommandService commands;

    VerticalController(
            VerticalService service,
            NodeCreationAdmission admission,
            NodeOperationService operations,
            ProjectPresentation presentation,
            NodeCommandService commands) {
        this.service = service;
        this.admission = admission;
        this.operations = operations;
        this.presentation = presentation;
        this.commands = commands;
    }

    @GetMapping("/health")
    Map<String, Object> health() {
        return Map.of(
                "status",
                "ok",
                "runtime",
                "spring",
                "virtual_threads",
                Thread.currentThread().isVirtual());
    }

    @GetMapping("/projects/{projectId}")
    WorkspaceViews.Project getProject(
            @PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return presentation.view(service.getProject(projectId, userId), userId);
    }

    @GetMapping("/projects/{projectId}/nodes/{nodeId}")
    NodeView getNode(
            @PathVariable long projectId,
            @PathVariable long nodeId,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.getNode(projectId, nodeId, userId);
    }

    @org.springframework.transaction.annotation.Transactional(
            readOnly = true,
            isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    @GetMapping("/projects/{projectId}/nodes")
    ResponseEntity<List<NodeView>> listNodes(
            @PathVariable long projectId,
            @RequestParam(value = "tag_ids", required = false) String tagIds,
            @RequestHeader(value = "If-None-Match", required = false) String etag,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        var nodes = service.listNodes(projectId, userId, tagIds);
        String current = presentation.graphEtag(projectId, nodes);
        return current.equals(etag)
                ? ResponseEntity.status(304).eTag(current).build()
                : ResponseEntity.ok()
                        .eTag(current)
                        .header("Cache-Control", "private, no-cache")
                        .body(nodes);
    }

    @DeleteMapping("/projects/{projectId}/nodes/{nodeId}")
    ResponseEntity<Void> deleteNode(
            @PathVariable long projectId,
            @PathVariable long nodeId,
            @RequestParam(required = false) Integer expected_version,
            @RequestParam(required = false) String scope_hash,
            @RequestHeader(value = "Idempotency-Key", required = false) String key,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        operations.delete(projectId, userId, nodeId, expected_version, scope_hash, key);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/projects/{projectId}/nodes/{nodeId}/activate")
    NodeView activate(
            @PathVariable long projectId,
            @PathVariable long nodeId,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.changeState(projectId, nodeId, userId, true);
    }

    @PostMapping("/projects/{projectId}/nodes/{nodeId}/deactivate")
    NodeView deactivate(
            @PathVariable long projectId,
            @PathVariable long nodeId,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.changeState(projectId, nodeId, userId, false);
    }

    @PostMapping("/projects/{projectId}/nodes")
    ResponseEntity<String> createNodes(
            @PathVariable long projectId,
            @RequestBody NodeCreate body,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        boolean ai = body.ai_prompt() != null && !body.ai_prompt().isEmpty();
        try (var permit = admission.enter(ai)) {
            VerticalService.CreateResult result =
                    service.createNodes(projectId, body, userId, idempotencyKey);
            return ResponseEntity.status(result.status())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(result.body());
        }
    }

    @PatchMapping("/projects/{projectId}/nodes/{nodeId}")
    NodeView patchNode(
            @PathVariable long projectId,
            @PathVariable long nodeId,
            @RequestBody NodePatch body,
            @RequestHeader(value = "Idempotency-Key", required = false) String key,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return commands.patch(projectId, userId, nodeId, body, key);
    }
}
