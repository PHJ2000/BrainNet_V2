package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceCommands.*;
import static com.brainnet.spring.WorkspaceViews.*;

import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
class WorkspaceProposalController {
    private final WorkspaceProposalService service;

    WorkspaceProposalController(WorkspaceProposalService service) {
        this.service = service;
    }

    @GetMapping("/health/ai")
    WorkerHealth health() {
        return service.health();
    }

    @GetMapping("/projects/{pid}/proposals")
    Page<Proposal, String> list(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestParam(required = false) String before) {
        return service.list(pid, uid, before);
    }

    @PostMapping("/projects/{pid}/proposals")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    Proposal request(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody ProposalCreate b,
            @RequestParam(defaultValue = "false") boolean enqueue) {
        return service.request(pid, uid, b, enqueue);
    }

    @GetMapping("/projects/{pid}/proposals/policy")
    Policy policy(@PathVariable long pid, @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return service.policy(pid, uid);
    }

    @PutMapping("/projects/{pid}/proposals/policy")
    Policy policy(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody PolicyUpdate b) {
        return service.policy(pid, uid, b);
    }

    @PostMapping("/projects/{pid}/proposals/{id}/cancel")
    Proposal cancel(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return service.cancel(pid, uid, id);
    }

    @PostMapping("/projects/{pid}/proposals/{id}/accept")
    Task accept(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody ProposalAccept b) {
        return service.accept(pid, uid, id, b);
    }
}
