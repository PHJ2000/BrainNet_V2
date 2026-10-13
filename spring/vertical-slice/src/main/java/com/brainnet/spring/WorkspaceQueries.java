package com.brainnet.spring;

import java.time.LocalDate;
import java.time.ZoneOffset;

/** Query strings stay strings until validation, preserving the API's 422 error contract. */
final class WorkspaceQueries {
    private WorkspaceQueries() {}

    record Tasks(
            String q,
            String status,
            String priority,
            String assignee,
            String before,
            String limit) {
        Tasks {
            status = defaultValue(status, "");
            priority = defaultValue(priority, "");
            assignee = defaultValue(assignee, "");
        }

        int pageSize() {
            return size(limit, 100, 200);
        }
    }

    record Personal(
            String scope,
            String status,
            String due,
            String today,
            String blocked,
            String q,
            String before,
            String limit) {
        Personal {
            scope = defaultValue(scope, "assigned");
            status = defaultValue(status, "open");
            due = defaultValue(due, "all");
            blocked = defaultValue(blocked, "false");
            q = defaultValue(q, "");
        }

        int pageSize() {
            return size(limit, 40, 100);
        }

        LocalDate date() {
            return parseDate(today);
        }
    }

    record Overview(String today) {
        LocalDate date() {
            return parseDate(today);
        }
    }

    record Discussions(String before, String limit, String thread_id) {
        int pageSize() {
            return size(limit, 50, 100);
        }
    }

    record Cursor(String before, String limit) {
        int pageSize() {
            return size(limit, 50, 100);
        }
    }

    record Knowledge(String q, String project_id, String after, String bookmarked, String limit) {
        Knowledge {
            q = defaultValue(q, "");
            project_id = defaultValue(project_id, "");
            after = defaultValue(after, "0");
            bookmarked = defaultValue(bookmarked, "false");
        }

        int pageSize() {
            return size(limit, 40, 100);
        }
    }

    private static String defaultValue(String value, String fallback) {
        return value == null ? fallback : value;
    }

    private static int size(String value, int fallback, int max) {
        try {
            int size = value == null ? fallback : Integer.parseInt(value);
            if (size < 1 || size > max) throw new IllegalArgumentException();
            return size;
        } catch (IllegalArgumentException exception) {
            throw WorkspaceInput.fail(422, "INVALID_INPUT", "Invalid limit");
        }
    }

    private static LocalDate parseDate(String value) {
        try {
            return value == null ? LocalDate.now(ZoneOffset.UTC) : LocalDate.parse(value);
        } catch (java.time.DateTimeException exception) {
            throw WorkspaceInput.fail(422, "INVALID_INPUT", "Invalid date");
        }
    }
}
