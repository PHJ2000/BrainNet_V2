package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceInput.*;

import com.fasterxml.jackson.annotation.JsonCreator;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.util.*;

/** Raw JSON is validated once here; application services receive explicit command types. */
final class WorkspaceCommands {
    private WorkspaceCommands() {}

    private static final JsonMapper JSON = new JsonMapper();
    private static final String[] TASK_FIELDS = {
        "title",
        "body",
        "status",
        "priority",
        "assignee_id",
        "due_date",
        "node_id",
        "checklist",
        "repeat_every_days"
    };

    private static void taskFields(Map<String, Object> input, String extra) {
        var allowed = new ArrayList<>(List.of(TASK_FIELDS));
        allowed.add(extra);
        fields(input, allowed.toArray(String[]::new));
    }

    record TaskCreate(String id, TaskFields fields) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static TaskCreate read(Map<String, Object> input) {
            taskFields(input, "id");
            return new TaskCreate(uuid(input.get("id")), TaskFields.parse(input));
        }
    }

    record TaskUpdate(
            long expectedVersion,
            TaskFields fields,
            boolean checklistProvided,
            boolean repeatProvided) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static TaskUpdate read(Map<String, Object> input) {
            taskFields(input, "expected_version");
            return new TaskUpdate(
                    integer(input, "expected_version", 0, Integer.MAX_VALUE, -1),
                    TaskFields.parse(input),
                    input.containsKey("checklist"),
                    input.containsKey("repeat_every_days"));
        }

        TaskFields resolve(TaskFields previous) {
            return new TaskFields(
                    fields.title(),
                    fields.body(),
                    fields.status(),
                    fields.priority(),
                    fields.assigneeId(),
                    fields.dueDate(),
                    fields.nodeId(),
                    checklistProvided ? fields.checklist() : previous.checklist(),
                    repeatProvided ? fields.repeatEveryDays() : previous.repeatEveryDays());
        }
    }

    record TaskVersion(String id, long expectedVersion) {}

    record BulkStatus(List<TaskVersion> tasks, String status) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static BulkStatus read(Map<String, Object> input) {
            fields(input, "tasks", "status");
            var tasks = new ArrayList<TaskVersion>();
            var ids = new HashSet<String>();
            for (var item : objects(input.get("tasks"), 100)) {
                fields(item, "id", "expected_version");
                String id = uuid(item.get("id"));
                if (!ids.add(id)) throw fail(422, "DUPLICATE_TASK", "Choose each task once");
                tasks.add(
                        new TaskVersion(
                                id, integer(item, "expected_version", 0, Integer.MAX_VALUE, -1)));
            }
            if (tasks.isEmpty()) throw fail(422, "INVALID_INPUT", "Choose tasks");
            return new BulkStatus(
                    List.copyOf(tasks),
                    choice(input, "status", null, "TODO", "DOING", "DONE", "CANCELED"));
        }
    }

    record Dependencies(long expectedVersion, List<String> requires) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static Dependencies read(Map<String, Object> input) {
            fields(input, "expected_version", "requires");
            if (!(input.get("requires") instanceof List<?> values) || values.size() > 50)
                throw fail(422, "INVALID_INPUT", "Too many prerequisites");
            return new Dependencies(
                    integer(input, "expected_version", 0, Integer.MAX_VALUE, -1),
                    values.stream().map(WorkspaceInput::uuid).toList());
        }
    }

    record DiscussionCreate(String id, String body, Long node_id) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static DiscussionCreate read(Map<String, Object> input) {
            fields(input, "id", "body", "node_id");
            return new DiscussionCreate(
                    uuid(input.get("id")),
                    text(input, "body", 1, 8000, null),
                    optionalId(input, "node_id"));
        }
    }

    record DiscussionUpdate(String body, boolean resolved, long expectedVersion) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static DiscussionUpdate read(Map<String, Object> input) {
            fields(input, "body", "resolved", "expected_version");
            if (!(input.get("resolved") instanceof Boolean resolved))
                throw fail(422, "INVALID_INPUT", "Resolved is required");
            return new DiscussionUpdate(
                    text(input, "body", 1, 8000, null),
                    resolved,
                    integer(input, "expected_version", 0, Integer.MAX_VALUE, -1));
        }
    }

    record ReplyCreate(String id, String body, List<Long> mentions) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static ReplyCreate read(Map<String, Object> input) {
            fields(input, "id", "body", "mentions");
            return new ReplyCreate(
                    uuid(input.get("id")),
                    text(input, "body", 1, 8000, null),
                    positiveIds(
                            input.getOrDefault("mentions", List.of()), 0, 20, "INVALID_MENTION"));
        }
    }

    record LinkCreate(long targetId, String label) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static LinkCreate read(Map<String, Object> input) {
            fields(input, "target_id", "label");
            return new LinkCreate(
                    integer(input, "target_id", 1, Long.MAX_VALUE, 0),
                    text(input, "label", 0, 120, ""));
        }
    }

    // Draft items are versioned JSON documents whose schema is selected by the URL's kind.
    record DraftSave(
            long expectedVersion,
            long baseVersion,
            boolean resolved,
            boolean attempted,
            JsonNode item) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static DraftSave read(Map<String, Object> input) {
            fields(input, "expected_version", "base_version", "resolved", "item", "attempted");
            if (!(input.get("item") instanceof Map<?, ?>))
                throw fail(422, "INVALID_DRAFT", "Missing item");
            return new DraftSave(
                    integer(input, "expected_version", -1, Integer.MAX_VALUE, -2),
                    integer(input, "base_version", -1, Integer.MAX_VALUE, -1),
                    bool(input.get("resolved")),
                    bool(input.get("attempted")),
                    JSON.valueToTree(input.get("item")));
        }

        void validateItem(String kind) {
            Map<String, Object> input = JSON.convertValue(item, Map.class);
            if (kind.equals("task")) TaskCreate.read(input);
            else DiscussionCreate.read(input);
        }
    }

    record ProposalCreate(String id, String mode, String instruction, List<Long> node_ids) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static ProposalCreate read(Map<String, Object> input) {
            fields(input, "id", "mode", "instruction", "node_ids");
            return new ProposalCreate(
                    uuid(input.get("id")),
                    choice(input, "mode", null, "EXPAND", "SUMMARY", "ACTION"),
                    text(input, "instruction", 0, 1000, ""),
                    positiveIds(input.get("node_ids"), 1, 8, "INVALID_INPUT"));
        }
    }

    record PolicyUpdate(long expectedVersion, long dailyLimit, long inputLimit) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static PolicyUpdate read(Map<String, Object> input) {
            fields(input, "expected_version", "daily_limit", "input_limit");
            return new PolicyUpdate(
                    integer(input, "expected_version", 0, Integer.MAX_VALUE, -1),
                    integer(input, "daily_limit", 0, 100, -1),
                    integer(input, "input_limit", 100, 16000, -1));
        }
    }

    record ProposalAccept(String title) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static ProposalAccept read(Map<String, Object> input) {
            fields(input, "title");
            return new ProposalAccept(text(input, "title", 1, 240, null));
        }
    }

    record AssetCreate(
            String id, String kind, String name, Long project_id, String q, boolean bookmarked) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static AssetCreate read(Map<String, Object> input) {
            fields(input, "id", "kind", "name", "project_id", "q", "bookmarked");
            return new AssetCreate(
                    uuid(input.get("id")),
                    choice(input, "kind", null, "SEARCH", "TEMPLATE"),
                    text(input, "name", 1, 80, null),
                    optionalId(input, "project_id"),
                    text(input, "q", 0, 200, ""),
                    bool(input.get("bookmarked")));
        }
    }

    record Undo(String previewHash) {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        static Undo read(Map<String, Object> input) {
            fields(input, "preview_hash");
            return new Undo(text(input, "preview_hash", 64, 64, null));
        }
    }

    private static List<Long> positiveIds(Object value, int min, int max, String code) {
        if (!(value instanceof List<?> values) || values.size() < min || values.size() > max)
            throw fail(422, code, "Invalid ID list");
        var result = new LinkedHashSet<Long>();
        for (Object item : values) {
            long id = integer(Collections.singletonMap("id", item), "id", 1, Long.MAX_VALUE, 0);
            if (!result.add(id)) throw fail(422, code, "Duplicate ID");
        }
        return List.copyOf(result);
    }
}
