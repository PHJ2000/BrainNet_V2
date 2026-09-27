package com.brainnet.spring;

import java.util.List;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/projects/{projectId}")
class VoteController {
    private final VoteService service;
    VoteController(VoteService service) { this.service = service; }

    @PostMapping("/tags/{tagId}/vote")
    VoteService.Vote cast(@PathVariable long projectId, @PathVariable long tagId,
                          @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.cast(projectId, tagId, userId);
    }

    @PostMapping("/votes/confirm")
    VoteService.History confirm(@PathVariable long projectId,
                               @RequestParam(value = "winning_tag_id", required = false) Long winningTagId,
                               @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.confirm(projectId, winningTagId, userId);
    }

    @GetMapping("/history")
    List<VoteService.History> history(@PathVariable long projectId, @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.history(projectId, userId);
    }

    @GetMapping("/history/{entryId}")
    VoteService.History entry(@PathVariable long projectId, @PathVariable long entryId,
                             @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.entry(projectId, entryId, userId);
    }
}
