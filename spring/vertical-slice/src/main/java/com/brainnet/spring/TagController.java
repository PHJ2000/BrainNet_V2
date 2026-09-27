package com.brainnet.spring;

import java.util.List;
import java.util.Map;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/projects/{projectId}/tags")
class TagController {
    private final TagService service;
    TagController(TagService service) { this.service = service; }

    @GetMapping
    List<TagService.View> list(@PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.list(projectId, userId);
    }

    @GetMapping("/{tagId}")
    TagService.View get(@PathVariable long projectId, @PathVariable long tagId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.get(projectId, tagId, userId);
    }

    @PostMapping
    ResponseEntity<TagService.View> create(@PathVariable long projectId, @Valid @RequestBody TagService.Create body,
                                          @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return ResponseEntity.status(201).body(service.create(projectId, userId, body));
    }

    @PatchMapping("/{tagId}")
    TagService.View update(@PathVariable long projectId, @PathVariable long tagId, @Valid @RequestBody TagService.Patch body,
                           @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.update(projectId, tagId, userId, body);
    }

    @DeleteMapping("/{tagId}")
    ResponseEntity<Void> delete(@PathVariable long projectId, @PathVariable long tagId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        service.delete(projectId, tagId, userId);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{tagId}/nodes/{nodeId}")
    Map<String, Object> attach(@PathVariable long projectId, @PathVariable long tagId, @PathVariable long nodeId,
                               @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.attach(projectId, tagId, nodeId, userId, true);
    }

    @DeleteMapping("/{tagId}/nodes/{nodeId}")
    Map<String, Object> detach(@PathVariable long projectId, @PathVariable long tagId, @PathVariable long nodeId,
                               @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.attach(projectId, tagId, nodeId, userId, false);
    }
}
