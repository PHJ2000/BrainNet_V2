package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceCommands.*;
import static com.brainnet.spring.WorkspaceInput.*;
import static com.brainnet.spring.WorkspaceViews.*;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;

@Service
class WorkspaceCollaborationService {
    private final ProjectAccessService access;
    private final ActivityService activity;

    final WorkspaceRepository repository;

    WorkspaceCollaborationService(
            ProjectAccessService access, ActivityService activity, WorkspaceRepository repository) {
        this.access = access;
        this.activity = activity;

        this.repository = repository;
    }

    @Transactional
    public Discussion createDiscussion(long pid, long uid, DiscussionCreate command) {
        access.lock(pid, uid, true);
        var hash = repository.requestHash(command);
        var old = repository.replay("discussion", command.id(), pid, uid, "author_id", hash);
        if (old != null) return repository.view(old, Discussion.class);
        repository.node(pid, command.node_id());
        repository.db.update(
                "INSERT INTO"
                    + " discussion(id,project_id,node_id,author_id,body,resolved,version,request_hash,created_at,updated_at)"
                    + " VALUES(?,?,?,?,?,false,0,?,now(),now())",
                command.id(),
                pid,
                command.node_id(),
                uid,
                command.body(),
                hash.current());
        activity.recordWorkspace(pid, uid, "discussion.created", command.id());
        return repository.view(repository.item("discussion", pid, command.id()), Discussion.class);
    }

    @Transactional
    public Discussion updateDiscussion(long pid, long uid, String id, DiscussionUpdate command) {
        var project = access.lock(pid, uid, true);
        var old = repository.item("discussion", pid, uuid(id));
        boolean author = old.get("author_id") != null && number(old.get("author_id")) == uid;
        if (!author && !command.body().equals(old.get("body")))
            throw fail(403, "AUTHOR_REQUIRED", "Only the author can edit text");
        if (!author && project.ownerId() != uid)
            throw fail(
                    403, "AUTHOR_OR_OWNER_REQUIRED", "Only author or owner may resolve discussion");
        repository.version(old, command.expectedVersion());
        repository.db.update(
                "UPDATE discussion SET body=?,resolved=?,version=version+1,updated_at=now() WHERE"
                    + " id=?",
                command.body(),
                command.resolved(),
                id);
        activity.recordWorkspace(pid, uid, "discussion.updated", id);
        return repository.view(repository.item("discussion", pid, id), Discussion.class);
    }

    @Transactional
    public Reply reply(long pid, long uid, String thread, ReplyCreate command) {
        access.lock(pid, uid, true);
        var discussion = repository.item("discussion", pid, uuid(thread));
        String id = command.id(), body = command.body();
        var mentions = command.mentions();
        var hash = repository.requestHash(command);
        var old = repository.replay("discussion_reply", id, pid, uid, "author_id", hash);
        if (old != null) {
            if (!thread.equals(old.get("discussion_id")))
                throw fail(409, "REQUEST_ID_REUSED", "Request belongs to another thread");
            return repository.view(old, Reply.class);
        }
        var members = new HashSet<Long>();
        for (var r :
                repository.rows("SELECT user_id FROM project_user_role WHERE project_id=?", pid))
            members.add(number(r.get("user_id")));
        if (!members.containsAll(mentions))
            throw fail(422, "INVALID_MENTION", "Mention current members only");
        repository.db.update(
                "INSERT INTO"
                    + " discussion_reply(id,project_id,discussion_id,author_id,body,mentions,request_hash,created_at)"
                    + " VALUES(?,?,?,?,?,?::jsonb,?,now())",
                id,
                pid,
                thread,
                uid,
                body,
                repository.encode(mentions),
                hash.current());
        var recipients = new HashSet<>(mentions);
        if (discussion.get("author_id") != null
                && members.contains(number(discussion.get("author_id"))))
            recipients.add(number(discussion.get("author_id")));
        recipients.remove(uid);
        for (long recipient : recipients)
            repository.db.update(
                    "INSERT INTO"
                        + " workspace_notification(user_id,project_id,discussion_id,reply_id,read,created_at)"
                        + " VALUES(?,?,?,?,false,now())",
                    recipient,
                    pid,
                    thread,
                    id);
        activity.recordWorkspace(pid, uid, "discussion.replied", id);
        return repository.view(repository.item("discussion_reply", pid, id), Reply.class);
    }

    Page<Notification, Long> inbox(long uid, Long before, boolean unread) {
        var args = new ArrayList<Object>();
        args.add(uid);
        args.add(uid);
        String filter = unread ? " AND n.read=false" : "";
        if (before != null) {
            filter += " AND n.id<?";
            args.add(before);
        }
        return repository.page(
                repository.rows(
                        "SELECT n.*,p.name project_name,left(r.body,300) preview FROM"
                            + " workspace_notification n JOIN project p ON p.id=n.project_id JOIN"
                            + " project_user_role m ON m.project_id=p.id AND m.user_id=? JOIN"
                            + " discussion_reply r ON r.id=n.reply_id WHERE n.user_id=? AND"
                            + " p.is_deleted=false"
                                + filter
                                + " ORDER BY n.id DESC LIMIT 51",
                        args.toArray()),
                50,
                Notification.class,
                Notification::id);
    }

    @Transactional
    public void read(long uid, long id) {
        var row =
                repository.one(
                        "SELECT * FROM workspace_notification WHERE id=? AND user_id=?", id, uid);
        if (row == null) throw fail(404, "NOTIFICATION_NOT_FOUND", "Notification not found");
        access.lock(number(row.get("project_id")), uid, false);
        repository.db.update("UPDATE workspace_notification SET read=true WHERE id=?", id);
    }

    Page<LinkItem, Long> links(long pid, long uid, long node, long after) {
        access.member(pid, uid);
        repository.node(pid, node);
        return repository.page(
                repository.rows(
                        "SELECT k.*,n.id node_id,left(n.content,1000) content,CASE WHEN"
                            + " k.source_id=? THEN 'outgoing' ELSE 'incoming' END direction FROM"
                            + " knowledge_link k JOIN node n ON (k.source_id=? AND"
                            + " n.id=k.target_id) OR (k.target_id=? AND n.id=k.source_id) WHERE"
                            + " n.project_id=? AND n.id>? ORDER BY n.id LIMIT 101",
                        node,
                        node,
                        node,
                        pid,
                        after),
                100,
                LinkItem.class,
                LinkItem::node_id);
    }

    @Transactional
    public Link link(long pid, long uid, long node, LinkCreate command) {
        access.lock(pid, uid, true);
        long target = command.targetId();
        String label = command.label();
        repository.node(pid, node);
        repository.node(pid, target);
        if (node == target) throw fail(422, "SELF_LINK", "Choose another node");
        if (repository.one(
                        "SELECT source_id FROM knowledge_link WHERE source_id=? AND target_id=?",
                        target,
                        node)
                != null) throw fail(409, "LINK_EXISTS", "Ideas are already connected");
        var old =
                repository.one(
                        "SELECT * FROM knowledge_link WHERE source_id=? AND target_id=?",
                        node,
                        target);
        if (old == null
                && repository.db.queryForObject(
                                "SELECT count(*) FROM knowledge_link WHERE source_id=?",
                                Long.class,
                                node)
                        >= 100) throw fail(422, "LINK_LIMIT", "At most 100 outgoing links");
        repository.db.update(
                "INSERT INTO knowledge_link(source_id,target_id,label,creator_id,created_at)"
                        + " VALUES(?,?,?,?,now()) ON CONFLICT(source_id,target_id) DO UPDATE SET"
                        + " label=excluded.label",
                node,
                target,
                label,
                uid);
        activity.recordWorkspace(pid, uid, "knowledge.linked", node);
        return repository.view(
                repository.one(
                        "SELECT * FROM knowledge_link WHERE source_id=? AND target_id=?",
                        node,
                        target),
                Link.class);
    }

    @Transactional
    public void unlink(long pid, long uid, long node, long target) {
        access.lock(pid, uid, true);
        repository.node(pid, node);
        repository.node(pid, target);
        repository.db.update(
                "DELETE FROM knowledge_link WHERE source_id=? AND target_id=?", node, target);
        activity.recordWorkspace(pid, uid, "knowledge.unlinked", node);
    }

    Draft draft(long pid, long uid, String kind) {
        kind(kind);
        access.member(pid, uid);
        var r =
                repository.one(
                        "SELECT * FROM workspace_draft WHERE user_id=? AND project_id=? AND kind=?",
                        uid,
                        pid,
                        kind);
        if (r != null && r.get("payload") instanceof Map<?, ?> p && bool(p.get("deleted")))
            r.put("payload", null);
        return repository.view(r, Draft.class);
    }

    void kind(String kind) {
        if (!Set.of("task", "discussion").contains(kind))
            throw fail(422, "INVALID_DRAFT", "Unknown draft kind");
    }

    @Transactional
    public Draft saveDraft(long pid, long uid, String kind, DraftSave command) {
        kind(kind);
        access.lock(pid, uid, true);
        command.validateItem(kind);
        long expected = command.expectedVersion();
        var old =
                repository.one(
                        "SELECT * FROM workspace_draft WHERE user_id=? AND project_id=? AND kind=?",
                        uid,
                        pid,
                        kind);
        if (old == null && expected != -1) throw fail(409, "VERSION_CONFLICT", "Draft changed");
        if (old != null) repository.version(old, expected);
        var payload =
                new DraftPayload(
                        command.item(),
                        command.attempted(),
                        command.baseVersion(),
                        command.resolved());
        repository.db.update(
                "INSERT INTO workspace_draft(user_id,project_id,kind,payload,version,updated_at)"
                    + " VALUES(?,?,?,?::jsonb,0,now()) ON CONFLICT(user_id,project_id,kind) DO"
                    + " UPDATE SET"
                    + " payload=excluded.payload,version=workspace_draft.version+1,updated_at=now()",
                uid,
                pid,
                kind,
                repository.encode(payload));
        return draft(pid, uid, kind);
    }

    @Transactional
    public void deleteDraft(long pid, long uid, String kind, int expected) {
        kind(kind);
        access.lock(pid, uid, true);
        var r =
                repository.one(
                        "SELECT * FROM workspace_draft WHERE user_id=? AND project_id=? AND kind=?",
                        uid,
                        pid,
                        kind);
        if (r != null) {
            repository.version(r, expected);
            repository.db.update(
                    "UPDATE workspace_draft SET payload='{"
                            + '"'
                            + "deleted"
                            + '"'
                            + ":true}'::jsonb,version=version+1,updated_at=now() WHERE user_id=?"
                            + " AND project_id=? AND kind=?",
                    uid,
                    pid,
                    kind);
        }
    }

    Page<Knowledge, Long> knowledge(long uid, WorkspaceQueries.Knowledge q) {
        String query = text(q.q(), "q", 0, 200);
        var args = new ArrayList<Object>();
        args.add(uid);
        args.add(uid);
        String filter = "";
        if (!q.project_id().isEmpty()) {
            long pid;
            try {
                pid = Long.parseLong(q.project_id());
            } catch (Exception e) {
                throw fail(422, "INVALID_INPUT", "Invalid project");
            }
            access.member(pid, uid);
            filter += " AND n.project_id=?";
            args.add(pid);
        }
        long after;
        try {
            after = Long.parseLong(q.after());
            if (after < 0) throw new IllegalArgumentException();
        } catch (Exception e) {
            throw fail(422, "INVALID_CURSOR", "Invalid cursor");
        }
        filter += " AND n.id>?";
        args.add(after);
        if (!query.isEmpty()) {
            filter += " AND n.content ILIKE ? ESCAPE '\\'";
            args.add(repository.like(query));
        }
        if (q.bookmarked().equals("true")) filter += " AND b.user_id IS NOT NULL";
        int limit = q.pageSize();
        args.add(limit + 1);
        return repository.page(
                repository.rows(
                        "SELECT n.id,n.project_id,p.name project_name,left(n.content,2000)"
                            + " content,n.version,n.state::text state,(b.user_id IS NOT NULL)"
                            + " bookmarked FROM node n JOIN project p ON p.id=n.project_id JOIN"
                            + " project_user_role m ON m.project_id=p.id AND m.user_id=? LEFT JOIN"
                            + " node_bookmark b ON b.node_id=n.id AND b.user_id=? WHERE"
                            + " p.is_deleted=false"
                                + filter
                                + " ORDER BY n.id LIMIT ?",
                        args.toArray()),
                limit,
                Knowledge.class,
                Knowledge::id);
    }

    @Transactional
    public void bookmark(long pid, long uid, long node, boolean add) {
        access.lock(pid, uid, false);
        repository.node(pid, node);
        if (add)
            repository.db.update(
                    "INSERT INTO node_bookmark(user_id,node_id,created_at) VALUES(?,?,now()) ON"
                            + " CONFLICT DO NOTHING",
                    uid,
                    node);
        else
            repository.db.update(
                    "DELETE FROM node_bookmark WHERE user_id=? AND node_id=?", uid, node);
    }

    @Transactional
    public RestoredProject restore(long pid, long uid) {
        var p =
                repository.one(
                        "SELECT * FROM project WHERE id=? AND owner_id=? FOR UPDATE", pid, uid);
        if (p == null) throw fail(404, "PROJECT_NOT_FOUND", "Project not found");
        if (bool(p.get("is_deleted"))) {
            repository.db.update(
                    "DELETE FROM invite_token WHERE project_id=? AND accepted_at IS NULL", pid);
            repository.db.update(
                    "UPDATE project SET is_deleted=false,updated_at=now() WHERE id=?", pid);
            activity.recordWorkspace(pid, uid, "project.restored", pid);
        }
        return new RestoredProject(pid, str(p.get("name")));
    }

    Page<Discussion, String> discussions(long pid, long uid, WorkspaceQueries.Discussions q) {
        access.member(pid, uid);
        return repository.list(
                "discussion",
                pid,
                q.before(),
                q.pageSize(),
                q.thread_id() != null ? " AND id=?" : "",
                q.thread_id() != null ? List.of(uuid(q.thread_id())) : List.of(),
                Discussion.class,
                Discussion::id);
    }

    Page<Reply, String> replies(long pid, long uid, String id, String before) {
        access.member(pid, uid);
        repository.item("discussion", pid, uuid(id));
        if (before != null
                && !id.equals(
                        repository.item("discussion_reply", pid, before).get("discussion_id")))
            throw fail(422, "INVALID_CURSOR", "Wrong thread");
        return repository.list(
                "discussion_reply",
                pid,
                before,
                50,
                " AND discussion_id=?",
                List.of(id),
                Reply.class,
                Reply::id);
    }

    Page<WorkspaceViews.Activity, Long> activity(long pid, long uid, Long before) {
        access.member(pid, uid);
        return repository.page(
                repository.rows(
                        "SELECT * FROM workspace_activity WHERE project_id=? AND id<? ORDER BY id"
                                + " DESC LIMIT 51",
                        pid,
                        before == null ? Long.MAX_VALUE : before),
                50,
                WorkspaceViews.Activity.class,
                WorkspaceViews.Activity::id);
    }

    List<TrashProject> trash(long uid) {
        return repository
                .rows(
                        "SELECT id,name,updated_at FROM project WHERE owner_id=? AND"
                            + " is_deleted=true ORDER BY updated_at DESC LIMIT 100",
                        uid)
                .stream()
                .map(row -> repository.view(row, TrashProject.class))
                .toList();
    }
}
