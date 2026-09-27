package com.brainnet.spring;

import java.util.List;
import java.util.Map;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
class AccountController {
    private final AccountService service;
    AccountController(AccountService service) { this.service = service; }

    @PostMapping("/auth/register")
    ResponseEntity<AccountService.User> register(@Valid @RequestBody AccountService.Register body) {
        return ResponseEntity.status(201).body(service.register(body));
    }

    @PostMapping(value = "/auth/login", consumes = MediaType.APPLICATION_FORM_URLENCODED_VALUE)
    Map<String, String> login(@RequestParam String username, @RequestParam String password) {
        return service.login(username, password);
    }

    @GetMapping("/users/me")
    AccountService.User me(@RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.me(userId);
    }

    @GetMapping("/users/me/tag-summaries")
    List<Map<String, Object>> summaries(@RequestAttribute(JwtAuthFilter.USER_ID) long userId) {
        return service.summaries(userId);
    }
}
