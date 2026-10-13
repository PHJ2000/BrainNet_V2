package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceInput.*;
import static com.brainnet.spring.WorkspaceViews.*;

import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
class NodeOperationController {
    final NodeOperationService operations;

    NodeOperationController(NodeOperationService operations) {
        this.operations = operations;
    }

    @GetMapping("/projects/{pid}/operations")
    Page<Operation, String> list(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @ModelAttribute WorkspaceQueries.Cursor q) {
        return operations.list(pid, uid, q.before(), q.pageSize());
    }

    @GetMapping("/projects/{pid}/operations/{id}/preview")
    OperationPreview preview(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return operations.preview(pid, uid, id);
    }

    @PostMapping("/projects/{pid}/operations/{id}/undo")
    UndoResult undo(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody WorkspaceCommands.Undo b) {
        return operations.undo(pid, uid, id, key, b.previewHash());
    }

    @GetMapping("/projects/{pid}/nodes/{node}/delete-preview")
    DeletePreview delete(
            @PathVariable long pid,
            @PathVariable long node,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return operations.deletePreview(pid, uid, node);
    }
}
