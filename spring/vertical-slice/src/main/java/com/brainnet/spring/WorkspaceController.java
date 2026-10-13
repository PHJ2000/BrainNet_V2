package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceCommands.*;
import static com.brainnet.spring.WorkspaceInput.*;
import static com.brainnet.spring.WorkspaceViews.*;

import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
class WorkspaceController {
    private final WorkspaceTaskService tasks;
    private final WorkspaceCollaborationService collaboration;

    WorkspaceController(WorkspaceTaskService tasks, WorkspaceCollaborationService collaboration) {
        this.tasks = tasks;
        this.collaboration = collaboration;
    }

    @GetMapping("/projects/{pid}/tasks")
    Page<Task, String> tasks(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @ModelAttribute WorkspaceQueries.Tasks q) {
        return tasks.list(pid, uid, q);
    }

    @GetMapping("/projects/{pid}/tasks/{id}")
    Task task(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return tasks.get(pid, uid, id);
    }

    @PostMapping("/projects/{pid}/tasks")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    Task create(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody TaskCreate b) {
        return tasks.create(pid, uid, b);
    }

    @PutMapping("/projects/{pid}/tasks/{id}")
    Task update(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody TaskUpdate b) {
        return tasks.update(pid, uid, id, b);
    }

    @PostMapping("/projects/{pid}/tasks/bulk-status")
    List<Task> bulk(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody BulkStatus b) {
        return tasks.bulk(pid, uid, b);
    }

    @GetMapping("/projects/{pid}/tasks/{id}/dependencies")
    List<Task> dependencies(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return tasks.dependencies(pid, uid, id);
    }

    @PutMapping("/projects/{pid}/tasks/{id}/dependencies")
    Task dependencies(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody Dependencies b) {
        return tasks.setDependencies(pid, uid, id, b);
    }

    @GetMapping("/workspace/tasks")
    PersonalTasks personal(
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @ModelAttribute WorkspaceQueries.Personal q) {
        return tasks.personal(uid, q);
    }

    @GetMapping("/projects/{pid}/overview")
    Overview overview(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @ModelAttribute WorkspaceQueries.Overview q) {
        return tasks.overview(pid, uid, q);
    }

    @GetMapping("/projects/{pid}/discussions")
    Page<Discussion, String> discussions(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @ModelAttribute WorkspaceQueries.Discussions q) {
        return collaboration.discussions(pid, uid, q);
    }

    @PostMapping("/projects/{pid}/discussions")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    Discussion discussion(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody DiscussionCreate b) {
        return collaboration.createDiscussion(pid, uid, b);
    }

    @PutMapping("/projects/{pid}/discussions/{id}")
    Discussion discussion(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody DiscussionUpdate b) {
        return collaboration.updateDiscussion(pid, uid, id, b);
    }

    @GetMapping("/projects/{pid}/discussions/{id}/replies")
    Page<Reply, String> replies(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestParam(required = false) String before) {
        return collaboration.replies(pid, uid, id, before);
    }

    @PostMapping("/projects/{pid}/discussions/{id}/replies")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    Reply reply(
            @PathVariable long pid,
            @PathVariable String id,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody ReplyCreate b) {
        return collaboration.reply(pid, uid, id, b);
    }

    @GetMapping("/projects/{pid}/activity")
    Page<WorkspaceViews.Activity, Long> activity(
            @PathVariable long pid,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestParam(required = false) Long before) {
        return collaboration.activity(pid, uid, before);
    }

    @GetMapping("/workspace/inbox")
    Page<Notification, Long> inbox(
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestParam(required = false) Long before,
            @RequestParam(defaultValue = "false") boolean unread) {
        return collaboration.inbox(uid, before, unread);
    }

    @PutMapping("/workspace/inbox/{id}/read")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    void read(@PathVariable long id, @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        collaboration.read(uid, id);
    }

    @GetMapping("/workspace/knowledge")
    Page<Knowledge, Long> knowledge(
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @ModelAttribute WorkspaceQueries.Knowledge q) {
        return collaboration.knowledge(uid, q);
    }

    @GetMapping("/projects/{pid}/knowledge/{node}/links")
    Page<LinkItem, Long> links(
            @PathVariable long pid,
            @PathVariable long node,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestParam(defaultValue = "0") long after) {
        return collaboration.links(pid, uid, node, after);
    }

    @PutMapping("/projects/{pid}/knowledge/{node}/links")
    Link link(
            @PathVariable long pid,
            @PathVariable long node,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody LinkCreate b) {
        return collaboration.link(pid, uid, node, b);
    }

    @DeleteMapping("/projects/{pid}/knowledge/{node}/links/{target}")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    void unlink(
            @PathVariable long pid,
            @PathVariable long node,
            @PathVariable long target,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        collaboration.unlink(pid, uid, node, target);
    }

    @PutMapping("/projects/{pid}/bookmarks/{node}")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    void bookmark(
            @PathVariable long pid,
            @PathVariable long node,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        collaboration.bookmark(pid, uid, node, true);
    }

    @DeleteMapping("/projects/{pid}/bookmarks/{node}")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    void unbookmark(
            @PathVariable long pid,
            @PathVariable long node,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        collaboration.bookmark(pid, uid, node, false);
    }

    @GetMapping("/projects/{pid}/drafts/{kind}")
    Draft draft(
            @PathVariable long pid,
            @PathVariable String kind,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return collaboration.draft(pid, uid, kind);
    }

    @PutMapping("/projects/{pid}/drafts/{kind}")
    Draft draft(
            @PathVariable long pid,
            @PathVariable String kind,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestBody DraftSave b) {
        return collaboration.saveDraft(pid, uid, kind, b);
    }

    @DeleteMapping("/projects/{pid}/drafts/{kind}")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    void deleteDraft(
            @PathVariable long pid,
            @PathVariable String kind,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestParam int expected_version) {
        collaboration.deleteDraft(pid, uid, kind, expected_version);
    }

    @GetMapping("/workspace/trash")
    List<TrashProject> trash(@RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return collaboration.trash(uid);
    }

    @PostMapping("/workspace/trash/{pid}/restore")
    RestoredProject restore(
            @PathVariable long pid, @RequestAttribute(JwtAuthFilter.USER_ID) long uid) {
        return collaboration.restore(pid, uid);
    }
}
