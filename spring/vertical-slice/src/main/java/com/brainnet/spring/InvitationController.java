package com.brainnet.spring;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
class InvitationController {
    private final InvitationService service;
    InvitationController(InvitationService service) { this.service = service; }

    @PostMapping("/projects/{projectId}/invite")
    InvitationService.Invitation invite(@PathVariable long projectId,
            @RequestParam @NotBlank @Email @Size(max = 120) String email,
            @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.invite(projectId, email, userId);
    }

    @PostMapping("/projects/join")
    Map<String, Object> join(@RequestParam @Pattern(regexp = "[A-Za-z0-9_-]{43}") String token,
                             @RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.join(token, userId);
    }
}
