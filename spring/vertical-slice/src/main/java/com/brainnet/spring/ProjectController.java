package com.brainnet.spring;

import jakarta.validation.Valid;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
class ProjectController {
    private final ProjectService service;
    private final ProjectPresentation presentation;

    ProjectController(ProjectService service, ProjectPresentation presentation) {
        this.service = service;
        this.presentation = presentation;
    }

    @GetMapping("/projects")
    List<WorkspaceViews.Project> list(
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId,
            @RequestParam(defaultValue = "false") boolean owned) {
        return service.list(userId, owned).stream().map(p -> presentation.view(p, userId)).toList();
    }

    @PostMapping("/projects")
    ResponseEntity<WorkspaceViews.Project> create(
            @Valid @RequestBody ProjectService.Create body,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return ResponseEntity.status(201)
                .body(presentation.view(service.create(body, userId), userId));
    }

    @RequestMapping(
            value = "/projects/{projectId}",
            method = {RequestMethod.PATCH, RequestMethod.PUT})
    WorkspaceViews.Project update(
            @PathVariable long projectId,
            @Valid @RequestBody ProjectService.Patch body,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return presentation.view(service.update(projectId, userId, body), userId);
    }

    @DeleteMapping("/projects/{projectId}")
    ResponseEntity<Void> delete(
            @PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        service.delete(projectId, userId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/projects/{projectId}/summary")
    Map<String, Object> summary(
            @PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.summary(projectId, userId);
    }
}
