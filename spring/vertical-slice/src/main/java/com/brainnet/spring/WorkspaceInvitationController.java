package com.brainnet.spring;

import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
class WorkspaceInvitationController {
    private final InvitationService invitations;

    WorkspaceInvitationController(InvitationService invitations) {
        this.invitations = invitations;
    }

    @GetMapping("/projects/{pid}/invitations")
    java.util.List<InvitationService.PendingInvitation> invitations(
            @PathVariable long pid, @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return invitations.list(pid, uid);
    }

    @DeleteMapping("/projects/{pid}/invitations")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    void revoke(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestParam String email) {
        invitations.revoke(pid, uid, email);
    }
}
