package com.brainnet.spring;

import static com.brainnet.spring.ApiModels.*;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestAttribute;
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

    @PatchMapping("/projects/{projectId}/nodes/{nodeId}")
    NodeView patchNode(@PathVariable long projectId, @PathVariable long nodeId,
                       @RequestBody NodePatch body,
                       @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.patchNode(projectId, nodeId, body, userId);
    }
}
