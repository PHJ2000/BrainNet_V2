package com.brainnet.spring;

import java.util.List;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/projects/{projectId}/tags/{tagId}")
class TagSummaryController {
    private final TagSummaryService service;
    TagSummaryController(TagSummaryService service) { this.service = service; }

    @PostMapping("/summary")
    TagSummaryService.Summary generate(@PathVariable long projectId, @PathVariable long tagId,
                                       @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.generate(projectId, tagId, userId);
    }

    @GetMapping("/summary")
    TagSummaryService.Summary latest(@PathVariable long projectId, @PathVariable long tagId,
                                     @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.latest(projectId, tagId, userId);
    }

    @GetMapping("/summaries")
    List<TagSummaryService.Summary> list(@PathVariable long projectId, @PathVariable long tagId,
                                         @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.list(projectId, tagId, userId);
    }
}
