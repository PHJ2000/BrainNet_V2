package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceCommands.*;
import static com.brainnet.spring.WorkspaceViews.*;

import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
@RequestMapping("/workspace/assets")
class WorkspaceAssetController {
    final WorkspaceAssetService service;

    WorkspaceAssetController(WorkspaceAssetService service) {
        this.service = service;
    }

    @GetMapping
    List<Asset> list(@RequestAttribute(JwtAuthFilter.USER_ID) long uid, @RequestParam String kind) {
        return service.list(uid, kind);
    }

    @PostMapping
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    Asset create(@RequestAttribute(JwtAuthFilter.USER_ID) long uid, @RequestBody AssetCreate b) {
        return service.create(uid, b);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    void delete(@RequestAttribute(JwtAuthFilter.USER_ID) long uid, @PathVariable String id) {
        service.delete(uid, id);
    }

    @PostMapping("/{id}/instantiate")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    ImportedProject instantiate(
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @PathVariable String id,
            @RequestHeader("Idempotency-Key") String key) {
        return service.instantiate(uid, id, key);
    }
}
