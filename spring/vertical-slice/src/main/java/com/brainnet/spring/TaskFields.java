package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceInput.*;

import java.time.LocalDate;
import java.util.*;

/** Shared task input contract for tasks, drafts, proposals and backups. */
record TaskFields(
        String title,
        String body,
        String status,
        String priority,
        Long assigneeId,
        LocalDate dueDate,
        Long nodeId,
        List<ChecklistItem> checklist,
        Long repeatEveryDays) {
    TaskFields {
        checklist = List.copyOf(checklist);
        if (repeatEveryDays != null && dueDate == null)
            throw fail(422, "REPEAT_NEEDS_DUE_DATE", "Repeating tasks need a due date");
    }

    record ChecklistItem(String id, String text, boolean done) {
        Map<String, Object> asMap() {
            return Map.of("id", id, "text", text, "done", done);
        }
    }

    static TaskFields parse(Map<String, Object> input) {
        String title = text(input, "title", 1, 240, null);
        String body = text(input, "body", 0, 12000, "");
        String status = choice(input, "status", "TODO", "TODO", "DOING", "DONE", "CANCELED");
        String priority = choice(input, "priority", "MEDIUM", "LOW", "MEDIUM", "HIGH");
        Long assignee = optionalId(input, "assignee_id"), node = optionalId(input, "node_id");
        LocalDate date = null;
        if (input.get("due_date") != null) {
            try {
                date = LocalDate.parse(str(input.get("due_date")));
                if (date.getYear() < 1 || date.getYear() > 9999)
                    throw new IllegalArgumentException();
            } catch (IllegalArgumentException | java.time.DateTimeException exception) {
                throw fail(422, "INVALID_INPUT", "Invalid due date");
            }
        }
        var checklist = new ArrayList<ChecklistItem>();
        var ids = new HashSet<String>();
        for (var item : objects(input.getOrDefault("checklist", List.of()), 50)) {
            fields(item, "id", "text", "done");
            String id = uuid(item.get("id"));
            if (!ids.add(id)) throw fail(422, "INVALID_INPUT", "Duplicate checklist ID");
            if (item.containsKey("done") && !(item.get("done") instanceof Boolean))
                throw fail(422, "INVALID_INPUT", "Invalid checklist state");
            checklist.add(
                    new ChecklistItem(
                            id, text(item, "text", 1, 240, null), bool(item.get("done"))));
        }
        Long repeat =
                input.get("repeat_every_days") == null
                        ? null
                        : integer(input, "repeat_every_days", 1, 365, 0);
        if (repeat != null && date == null)
            throw fail(422, "REPEAT_NEEDS_DUE_DATE", "Repeating tasks need a due date");
        return new TaskFields(
                title,
                body,
                status,
                priority,
                assignee,
                date,
                node,
                List.copyOf(checklist),
                repeat);
    }

    void requireCompleteChecklist() {
        if (status.equals("DONE") && checklist.stream().anyMatch(item -> !item.done()))
            throw fail(409, "CHECKLIST_INCOMPLETE", "Complete all checklist items first");
    }

    static TaskFields stored(Map<String, Object> row) {
        return parse(row).withText((String) row.get("title"), (String) row.get("body"));
    }

    TaskFields withText(String title, String body) {
        return new TaskFields(
                title,
                body,
                status,
                priority,
                assigneeId,
                dueDate,
                nodeId,
                checklist,
                repeatEveryDays);
    }

    TaskFields withStatus(String status) {
        return new TaskFields(
                title,
                body,
                status,
                priority,
                assigneeId,
                dueDate,
                nodeId,
                checklist,
                repeatEveryDays);
    }

    Map<String, Object> asMap() {
        var fields = new LinkedHashMap<String, Object>();
        fields.put("title", title);
        fields.put("body", body);
        fields.put("status", status);
        fields.put("priority", priority);
        fields.put("assignee_id", assigneeId);
        fields.put("due_date", dueDate == null ? null : dueDate.toString());
        fields.put("node_id", nodeId);
        fields.put("checklist", checklist.stream().map(ChecklistItem::asMap).toList());
        fields.put("repeat_every_days", repeatEveryDays);
        return fields;
    }
}
