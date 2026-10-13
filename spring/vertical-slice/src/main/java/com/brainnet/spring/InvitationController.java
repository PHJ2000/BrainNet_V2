package com.brainnet.spring;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
class InvitationController {
    private final InvitationService service;

    InvitationController(InvitationService service) {
        this.service = service;
    }

    @PostMapping("/projects/{projectId}/invite")
    InvitationService.Invitation invite(
            @PathVariable long projectId,
            @RequestParam @NotBlank @Email @Size(max = 120) String email,
            @RequestParam(defaultValue = "EDITOR") String role,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.invite(projectId, email, userId, role);
    }

    record Join(String token) {
        @com.fasterxml.jackson.annotation.JsonCreator(
                mode = com.fasterxml.jackson.annotation.JsonCreator.Mode.DELEGATING)
        static Join read(Map<String, Object> input) {
            return new Join(WorkspaceInput.text(input, "token", 43, 43, null));
        }
    }

    @PostMapping("/projects/join")
    Map<String, Object> join(
            @RequestParam(required = false) String token,
            @RequestBody(required = false) Join body,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        String value = body != null ? WorkspaceInput.text(body.token(), "token", 43, 43) : token;
        if (value == null || !value.matches("[A-Za-z0-9_-]{43}"))
            throw WorkspaceInput.fail(422, "INVALID_INPUT", "Invalid invitation token");
        return service.join(value, userId);
    }
}
