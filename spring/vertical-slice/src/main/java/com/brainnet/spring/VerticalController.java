package com.brainnet.spring;

import static com.brainnet.spring.ApiModels.*;

import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
class VerticalController {
    private final VerticalService service;

    VerticalController(VerticalService service) {
        this.service = service;
    }

    @GetMapping("/health")
    Map<String, Object> health() {
        return Map.of("status", "ok", "runtime", "spring", "virtual_threads", Thread.currentThread().isVirtual());
    }

    @GetMapping("/projects/{projectId}")
    ProjectView getProject(@PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.getProject(projectId, userId);
    }

    @GetMapping("/projects/{projectId}/nodes/{nodeId}")
    NodeView getNode(@PathVariable long projectId, @PathVariable long nodeId,
                     @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.getNode(projectId, nodeId, userId);
    }

    @PostMapping("/projects/{projectId}/nodes")
    ResponseEntity<String> createNodes(
            @PathVariable long projectId,
            @RequestBody NodeCreate body,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        VerticalService.CreateResult result = service.createNodes(projectId, body, userId, idempotencyKey);
        return ResponseEntity.status(result.status()).contentType(MediaType.APPLICATION_JSON).body(result.body());
    }

    @PatchMapping("/projects/{projectId}/nodes/{nodeId}")
    NodeView patchNode(@PathVariable long projectId, @PathVariable long nodeId,
                       @RequestBody NodePatch body,
                       @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.patchNode(projectId, nodeId, body, userId);
    }
}
