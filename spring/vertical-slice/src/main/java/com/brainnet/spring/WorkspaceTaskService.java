package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceCommands.*;
import static com.brainnet.spring.WorkspaceInput.*;
import static com.brainnet.spring.WorkspaceViews.*;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.*;
import java.util.*;

@Service
class WorkspaceTaskService {
    private final ProjectAccessService access;
    private final ActivityService activity;

    final WorkspaceRepository repository;

    WorkspaceTaskService(
            ProjectAccessService access, ActivityService activity, WorkspaceRepository repository) {
        this.access = access;
        this.activity = activity;

        this.repository = repository;
    }

    static final String BLOCKED =
            "EXISTS(SELECT 1 FROM task_dependency d JOIN work_item r ON r.id=d.requires_id WHERE"
                    + " d.task_id=t.id AND r.status<>'DONE')";

    void links(long pid, TaskFields b) {
        repository.node(pid, b.nodeId());
        if (b.assigneeId() != null
                && repository.one(
                                "SELECT user_id FROM project_user_role WHERE project_id=? AND"
                                        + " user_id=? AND role::text IN ('OWNER','EDITOR')",
                                pid,
                                b.assigneeId())
                        == null)
            throw fail(422, "INVALID_ASSIGNEE", "Choose a current editor or owner");
    }

    Task insert(long pid, long uid, String id, TaskFields b, String hash, String parent) {
        repository.db.update(
                "INSERT INTO"
                    + " work_item(id,project_id,creator_id,title,body,status,priority,assignee_id,due_date,node_id,checklist,repeat_every_days,recurrence_parent_id,version,request_hash,created_at,updated_at)"
                    + " VALUES(?,?,?,?,?,?,?,?,?::date,?,?::jsonb,?,?,0,?,now(),now())",
                id,
                pid,
                uid,
                b.title(),
                b.body(),
                b.status(),
                b.priority(),
                b.assigneeId(),
                b.dueDate(),
                b.nodeId(),
                repository.encode(b.checklist()),
                b.repeatEveryDays(),
                parent,
                hash);
        activity.recordWorkspace(pid, uid, "task.created", id);
        return repository.view(repository.item("work_item", pid, id), Task.class);
    }

    @Transactional
    public Task create(long pid, long uid, TaskCreate command) {
        access.lock(pid, uid, true);
        String id = command.id();
        TaskFields fields = command.fields();
        var hash = repository.taskRequestHash(id, fields);
        var old = repository.replay("work_item", id, pid, uid, "creator_id", hash);
        if (old != null) return repository.view(old, Task.class);
        links(pid, fields);
        fields.requireCompleteChecklist();
        return insert(pid, uid, id, fields, hash.current(), null);
    }

    void dependencies(String id, String status, Set<String> batch) {
        String sql =
                status.equals("DONE")
                        ? "SELECT r.id FROM task_dependency d JOIN work_item r ON"
                                + " r.id=d.requires_id WHERE d.task_id=? AND r.status<>'DONE'"
                        : "SELECT t.id FROM task_dependency d JOIN work_item t ON t.id=d.task_id"
                                + " WHERE d.requires_id=? AND t.status='DONE'";
        if (repository.rows(sql, id).stream().anyMatch(r -> !batch.contains(str(r.get("id")))))
            throw fail(
                    409,
                    status.equals("DONE") ? "TASK_BLOCKED" : "TASK_DEPENDENTS_DONE",
                    "Prerequisite status prevents this change");
    }

    void repeat(long pid, long uid, String id, TaskFields fields, String previous) {
        fields.requireCompleteChecklist();
        if (!fields.status().equals("DONE")
                || previous.equals("DONE")
                || fields.repeatEveryDays() == null) return;
        if (repository.one("SELECT id FROM work_item WHERE recurrence_parent_id=?", id) != null)
            return;
        LocalDate due;
        try {
            due = fields.dueDate().plusDays(fields.repeatEveryDays());
            if (due.getYear() > 9999) throw new IllegalArgumentException();
        } catch (java.time.DateTimeException | IllegalArgumentException exception) {
            throw fail(422, "INVALID_REPEAT_DATE", "Next deadline is outside supported dates");
        }
        Long assignee = fields.assigneeId();
        if (assignee != null
                && repository.one(
                                "SELECT user_id FROM project_user_role WHERE project_id=? AND"
                                    + " user_id=? AND role::text<>'VIEWER'",
                                pid,
                                assignee)
                        == null) assignee = null;
        var checklist =
                fields.checklist().stream()
                        .map(
                                item ->
                                        new TaskFields.ChecklistItem(
                                                UUID.randomUUID().toString(), item.text(), false))
                        .toList();
        var next =
                new TaskFields(
                        fields.title(),
                        fields.body(),
                        "TODO",
                        fields.priority(),
                        assignee,
                        due,
                        fields.nodeId(),
                        checklist,
                        fields.repeatEveryDays());
        insert(
                pid,
                uid,
                UUID.randomUUID().toString(),
                next,
                repository.hash(Map.of("recurrence", id)),
                id);
    }

    void write(long pid, String id, TaskFields n) {
        repository.db.update(
                "UPDATE work_item SET"
                    + " title=?,body=?,status=?,priority=?,assignee_id=?,due_date=?::date,node_id=?,checklist=?::jsonb,repeat_every_days=?,version=version+1,updated_at=now()"
                    + " WHERE project_id=? AND id=?",
                n.title(),
                n.body(),
                n.status(),
                n.priority(),
                n.assigneeId(),
                n.dueDate(),
                n.nodeId(),
                repository.encode(n.checklist()),
                n.repeatEveryDays(),
                pid,
                id);
    }

    @Transactional
    public Task update(long pid, long uid, String id, TaskUpdate command) {
        access.lock(pid, uid, true);
        var old = repository.item("work_item", pid, uuid(id));
        repository.version(old, command.expectedVersion());
        TaskFields fields = command.resolve(TaskFields.stored(old));
        links(pid, fields);
        dependencies(id, fields.status(), Set.of());
        repeat(pid, uid, id, fields, str(old.get("status")));
        write(pid, id, fields);
        activity.recordWorkspace(pid, uid, "task.updated", id);
        return repository.view(repository.item("work_item", pid, id), Task.class);
    }

    @Transactional
    public List<Task> bulk(long pid, long uid, BulkStatus command) {
        access.lock(pid, uid, true);
        var ids =
                command.tasks().stream()
                        .map(TaskVersion::id)
                        .collect(java.util.stream.Collectors.toSet());
        var result = new ArrayList<Task>();
        for (var task : command.tasks()) {
            var old = repository.item("work_item", pid, task.id());
            repository.version(old, task.expectedVersion());
            dependencies(task.id(), command.status(), ids);
            var fields = TaskFields.stored(old).withStatus(command.status());
            repeat(pid, uid, task.id(), fields, str(old.get("status")));
            write(pid, task.id(), fields);
            activity.recordWorkspace(pid, uid, "task.updated", task.id());
            result.add(repository.view(repository.item("work_item", pid, task.id()), Task.class));
        }
        return result;
    }

    @Transactional
    public Task setDependencies(long pid, long uid, String id, Dependencies command) {
        access.lock(pid, uid, true);
        uuid(id);
        var row = repository.item("work_item", pid, id);
        repository.version(row, command.expectedVersion());
        var requires = new HashSet<String>();
        for (String target : command.requires()) {
            var required = repository.item("work_item", pid, target);
            if ("DONE".equals(row.get("status")) && !"DONE".equals(required.get("status")))
                throw fail(409, "TASK_BLOCKED", "Incomplete prerequisite");
            requires.add(target);
        }
        var graph = new HashMap<String, Set<String>>();
        for (var edge :
                repository.rows(
                        "SELECT d.* FROM task_dependency d JOIN work_item t ON t.id=d.task_id WHERE"
                                + " t.project_id=?",
                        pid))
            graph.computeIfAbsent(str(edge.get("task_id")), k -> new HashSet<>())
                    .add(str(edge.get("requires_id")));
        graph.put(id, requires);
        var pending = new ArrayDeque<>(requires);
        var seen = new HashSet<String>();
        while (!pending.isEmpty()) {
            String candidate = pending.pop();
            if (candidate.equals(id)) throw fail(422, "DEPENDENCY_CYCLE", "Circular prerequisites");
            if (seen.add(candidate)) pending.addAll(graph.getOrDefault(candidate, Set.of()));
        }
        repository.db.update("DELETE FROM task_dependency WHERE task_id=?", id);
        for (String target : requires)
            repository.db.update(
                    "INSERT INTO task_dependency(task_id,requires_id) VALUES(?,?)", id, target);
        repository.db.update(
                "UPDATE work_item SET version=version+1,updated_at=now() WHERE id=?", id);
        activity.recordWorkspace(pid, uid, "task.dependencies", id);
        return repository.view(repository.item("work_item", pid, id), Task.class);
    }

    Page<Task, String> list(long pid, long uid, WorkspaceQueries.Tasks q) {
        access.member(pid, uid);
        StringBuilder extra = new StringBuilder();
        var args = new ArrayList<Object>();
        if (q.q() != null) {
            String query = text(q.q(), "q", 0, 200);
            extra.append(" AND title ILIKE ? ESCAPE '\\'");
            args.add(repository.like(query));
        }
        if (!q.status().isEmpty()) {
            extra.append(" AND status=?");
            args.add(choice(q.status(), "status", "TODO", "DOING", "DONE", "CANCELED"));
        }
        if (!q.priority().isEmpty()) {
            extra.append(" AND priority=?");
            args.add(choice(q.priority(), "priority", "LOW", "MEDIUM", "HIGH"));
        }
        String assignee = q.assignee();
        if (!assignee.isEmpty()) {
            if (assignee.equals("none")) extra.append(" AND assignee_id IS NULL");
            else {
                try {
                    args.add(Long.parseLong(assignee));
                } catch (Exception e) {
                    throw fail(422, "INVALID_ASSIGNEE", "Invalid assignee");
                }
                extra.append(" AND assignee_id=?");
            }
        }
        return repository.list(
                "work_item",
                pid,
                q.before(),
                q.pageSize(),
                extra.toString(),
                args,
                Task.class,
                Task::id);
    }

    PersonalTasks personal(long uid, WorkspaceQueries.Personal q) {
        String scope = choice(q.scope(), "scope", "assigned", "created", "all");
        String status =
                choice(q.status(), "status", "open", "all", "TODO", "DOING", "DONE", "CANCELED");
        String due = choice(q.due(), "due", "all", "overdue", "today", "week", "none");
        LocalDate today = q.date();
        String base =
                " FROM work_item t JOIN project p ON p.id=t.project_id JOIN project_user_role m ON"
                        + " m.project_id=p.id AND m.user_id=? WHERE p.is_deleted=false";
        var args = new ArrayList<Object>();
        args.add(uid);
        StringBuilder where = new StringBuilder(base);
        if (!scope.equals("all")) {
            where.append(scope.equals("assigned") ? " AND t.assignee_id=?" : " AND t.creator_id=?");
            args.add(uid);
        }
        if (status.equals("open")) where.append(" AND t.status IN ('TODO','DOING')");
        else if (!status.equals("all")) {
            where.append(" AND t.status=?");
            args.add(status);
        }
        if (due.equals("none")) where.append(" AND due_date IS NULL");
        else if (!due.equals("all")) {
            where.append(
                    due.equals("overdue")
                            ? " AND due_date<?::date"
                            : due.equals("today")
                                    ? " AND due_date=?::date"
                                    : " AND due_date BETWEEN ?::date AND ?::date");
            args.add(today.toString());
            if (due.equals("week"))
                args.add(
                        today.plusDays(
                                        Math.min(
                                                6,
                                                java.time.temporal.ChronoUnit.DAYS.between(
                                                        today, LocalDate.of(9999, 12, 31))))
                                .toString());
        }
        if (q.blocked().equals("true"))
            where.append(" AND t.status IN ('TODO','DOING') AND " + BLOCKED);
        if (!q.q().isEmpty()) {
            where.append(" AND t.title ILIKE ? ESCAPE '\\'");
            args.add(repository.like(text(q.q(), "q", 0, 200)));
        }
        if (q.before() != null) {
            String id = uuid(q.before());
            var cursor = repository.one("SELECT t.id,t.due_date" + base + " AND t.id=?", uid, id);
            if (cursor == null) throw fail(422, "INVALID_CURSOR", "Cursor unavailable");
            where.append(" AND (COALESCE(t.due_date,'9999-12-31'::date),t.id)>(?::date,?)");
            args.add(cursor.get("due_date") == null ? "9999-12-31" : cursor.get("due_date"));
            args.add(id);
        }
        int limit = q.pageSize();
        args.add(limit + 1);
        var result =
                repository.page(
                        repository.rows(
                                "SELECT t.*,p.name project_name,m.role::text my_role,"
                                        + BLOCKED
                                        + " blocked"
                                        + where
                                        + " ORDER BY COALESCE(t.due_date,'9999-12-31'::date),t.id"
                                        + " LIMIT ?",
                                args.toArray()),
                        limit,
                        PersonalTask.class,
                        PersonalTask::id);
        return new PersonalTasks(result.items(), result.next_cursor(), today.toString());
    }

    Overview overview(long pid, long uid, WorkspaceQueries.Overview q) {
        access.member(pid, uid);
        LocalDate today = q.date();
        LocalDate week =
                today.plusDays(
                        Math.min(
                                6,
                                java.time.temporal.ChronoUnit.DAYS.between(
                                        today, LocalDate.of(9999, 12, 31))));
        String open = "t.status IN ('TODO','DOING')";
        var counts =
                repository.one(
                        "SELECT count(*) total,count(*) FILTER(WHERE status='TODO') todo,count(*)"
                                + " FILTER(WHERE status='DOING') doing,count(*) FILTER(WHERE"
                                + " status='DONE') done,count(*) FILTER(WHERE status='CANCELED')"
                                + " canceled,count(*) FILTER(WHERE "
                                + open
                                + " AND due_date<?::date) overdue,count(*) FILTER(WHERE "
                                + open
                                + " AND due_date=?::date) due_today,count(*) FILTER(WHERE "
                                + open
                                + " AND due_date BETWEEN ?::date AND ?::date) due_week,count(*)"
                                + " FILTER(WHERE "
                                + open
                                + " AND "
                                + BLOCKED
                                + ") blocked FROM work_item t WHERE project_id=?",
                        today.toString(),
                        today.toString(),
                        today.toString(),
                        week.toString(),
                        pid);
        var workload =
                repository.rows(
                        "SELECT t.assignee_id,u.email,count(*) open,count(*) FILTER(WHERE"
                                + " t.due_date<?::date) overdue FROM work_item t LEFT JOIN"
                                + " project_user_role m ON m.project_id=t.project_id AND"
                                + " m.user_id=t.assignee_id LEFT JOIN app_user u ON u.id=m.user_id"
                                + " WHERE t.project_id=? AND "
                                + open
                                + " GROUP BY t.assignee_id,u.email ORDER BY count(*)"
                                + " DESC,t.assignee_id NULLS FIRST LIMIT 101",
                        today.toString(),
                        pid);
        return new Overview(
                today.toString(),
                repository.view(counts, Counts.class),
                workload.stream()
                        .limit(100)
                        .map(row -> repository.view(row, Workload.class))
                        .toList(),
                workload.size() > 100,
                repository
                        .rows(
                                "SELECT * FROM work_item t WHERE project_id=? AND "
                                        + open
                                        + " AND due_date IS NOT NULL ORDER BY due_date,id LIMIT 10",
                                pid)
                        .stream()
                        .map(row -> repository.view(row, Task.class))
                        .toList());
    }

    Task get(long pid, long uid, String id) {
        access.member(pid, uid);
        return repository.view(repository.item("work_item", pid, uuid(id)), Task.class);
    }

    List<Task> dependencies(long pid, long uid, String id) {
        access.member(pid, uid);
        repository.item("work_item", pid, uuid(id));
        return repository
                .rows(
                        "SELECT t.* FROM work_item t JOIN task_dependency d ON d.requires_id=t.id"
                                + " WHERE d.task_id=? ORDER BY t.title",
                        id)
                .stream()
                .map(row -> repository.view(row, Task.class))
                .toList();
    }
}
