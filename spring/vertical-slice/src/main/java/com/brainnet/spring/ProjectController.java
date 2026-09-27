package com.brainnet.spring;

import java.util.List;
import java.util.Map;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
class ProjectController {
    private final ProjectService service;
    ProjectController(ProjectService service) { this.service = service; }

    @GetMapping("/projects")
    List<ApiModels.ProjectView> list(@RequestAttribute(JwtAuthFilter.USER_ID) long userId,
                                    @RequestParam(defaultValue = "false") boolean owned) {
        return service.list(userId, owned);
    }

    @PostMapping("/projects")
    ResponseEntity<ApiModels.ProjectView> create(@Valid @RequestBody ProjectService.Create body,
                                               @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return ResponseEntity.status(201).body(service.create(body, userId));
    }

    @RequestMapping(value = "/projects/{projectId}", method = {RequestMethod.PATCH, RequestMethod.PUT})
    ApiModels.ProjectView update(@PathVariable long projectId, @Valid @RequestBody ProjectService.Patch body,
                                 @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.update(projectId, userId, body);
    }

    @DeleteMapping("/projects/{projectId}")
    ResponseEntity<Void> delete(@PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        service.delete(projectId, userId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/projects/{projectId}/summary")
    Map<String, Object> summary(@PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.summary(projectId, userId);
    }
}
