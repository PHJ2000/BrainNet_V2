package com.brainnet.vertical;

import static com.brainnet.vertical.ApiModels.*;

import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
class VerticalController {
    private final VerticalService service;
    VerticalController(VerticalService service) { this.service = service; }

    @GetMapping("/health") Map<String, Object> health() {
        return Map.of("status", "ok", "runtime", "spring", "virtual_threads", Thread.currentThread().isVirtual());
    }

    @PostMapping(value = "/projects", produces = "application/json")
    @ResponseStatus(HttpStatus.CREATED)
    ProjectView createProject(@Valid @RequestBody ProjectCreate body,
                              @RequestHeader(value = "X-User-Id", defaultValue = "1") long userId,
                              @RequestHeader(value = "X-Benchmark-Fault", required = false) String fault) {
        return service.createProject(body, userId, "db".equals(fault));
    }

    @PostMapping("/projects/{projectId}/nodes")
    @ResponseStatus(HttpStatus.CREATED)
    NodeView createNode(@PathVariable long projectId, @Valid @RequestBody NodeCreate body,
                        @RequestHeader(value = "X-User-Id", defaultValue = "1") long userId) {
        return service.createNode(projectId, body, userId);
    }

    @GetMapping("/projects/{projectId}/nodes/{nodeId}")
    NodeView getNode(@PathVariable long projectId, @PathVariable long nodeId) { return service.getNode(projectId, nodeId); }

    @PatchMapping("/projects/{projectId}/nodes/{nodeId}")
    NodeView patchNode(@PathVariable long projectId, @PathVariable long nodeId,
                       @Valid @RequestBody NodePatch body,
                       @RequestHeader(value = "X-Benchmark-Fault", required = false) String fault) {
        return service.patchNode(projectId, nodeId, body, "db".equals(fault));
    }

    @PostMapping("/benchmark/reset")
    ResetView reset(@RequestParam(defaultValue = "400") int nodes, @RequestParam(defaultValue = "true") boolean root) {
        return service.reset(nodes, root);
    }

    @GetMapping("/benchmark/state") StateView state() { return service.state(); }
}
