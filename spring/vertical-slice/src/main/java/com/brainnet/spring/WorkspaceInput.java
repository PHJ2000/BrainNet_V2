package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;

import org.springframework.http.HttpStatus;

import java.nio.charset.StandardCharsets;
import java.util.*;

/** Validation and object projections shared by workspace request boundaries. */
final class WorkspaceInput {
    private WorkspaceInput() {}

    static ApiException fail(int status, String code, String message) {
        return new ApiException(HttpStatus.valueOf(status), code, message);
    }

    static long number(Object x) {
        return x instanceof Number n ? n.longValue() : Long.parseLong(x.toString());
    }

    static String str(Object x) {
        return x == null ? "" : x.toString();
    }

    static boolean bool(Object x) {
        return Boolean.TRUE.equals(x);
    }

    static String text(Map<String, Object> b, String key, int min, int max, String fallback) {
        Object value = b.getOrDefault(key, fallback);
        if (!(value instanceof String)) throw fail(422, "INVALID_INPUT", key + " must be text");
        String s = ((String) value).strip();
        if (!validText(s, min, max)) throw fail(422, "INVALID_INPUT", "Invalid " + key);
        return s;
    }

    static String text(String value, String key, int min, int max) {
        if (value == null) throw fail(422, "INVALID_INPUT", key + " must be text");
        String normalized = value.strip();
        if (!validText(normalized, min, max)) throw fail(422, "INVALID_INPUT", "Invalid " + key);
        return normalized;
    }

    static String choice(String value, String key, String... allowed) {
        String normalized = text(value, key, 0, 50);
        if (!Set.of(allowed).contains(normalized))
            throw fail(422, "INVALID_INPUT", "Invalid " + key);
        return normalized;
    }

    static boolean validText(String value, int min, int max) {
        int length = value.codePointCount(0, value.length());
        return length >= min
                && length <= max
                && value.indexOf('\0') < 0
                && StandardCharsets.UTF_8.newEncoder().canEncode(value);
    }

    static String choice(Map<String, Object> b, String key, String fallback, String... allowed) {
        String s = text(b, key, 0, 50, fallback);
        if (!Set.of(allowed).contains(s)) throw fail(422, "INVALID_INPUT", "Invalid " + key);
        return s;
    }

    static String uuid(Object x) {
        try {
            return UUID.fromString(str(x)).toString();
        } catch (Exception e) {
            throw fail(422, "INVALID_INPUT", "Valid UUID required");
        }
    }

    static long integer(Map<String, Object> b, String key, long min, long max, long fallback) {
        Object x = b.getOrDefault(key, fallback);
        if (!(x instanceof Number n)
                || n.doubleValue() != n.longValue()
                || n.longValue() < min
                || n.longValue() > max) throw fail(422, "INVALID_INPUT", "Invalid " + key);
        return n.longValue();
    }

    static Long optionalId(Map<String, Object> b, String key) {
        return b.get(key) == null ? null : integer(b, key, 1, Long.MAX_VALUE, 0);
    }

    @SuppressWarnings("unchecked")
    static List<Map<String, Object>> objects(Object x, int max) {
        if (!(x instanceof List<?> l)
                || l.size() > max
                || l.stream().anyMatch(v -> !(v instanceof Map)))
            throw fail(422, "INVALID_INPUT", "Invalid list");
        return (List<Map<String, Object>>) x;
    }

    static void fields(Map<String, Object> b, String... keys) {
        if (!Set.of(keys).containsAll(b.keySet()))
            throw fail(422, "INVALID_INPUT", "Unknown field");
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> map(Object o) {
        if (!(o instanceof Map<?, ?>)) throw fail(422, "INVALID_INPUT", "Expected object");
        return (Map<String, Object>) o;
    }

    static Map<String, Object> pick(Map<String, Object> r, String... keys) {
        var out = new LinkedHashMap<String, Object>();
        for (String key : keys) out.put(key, r.get(key));
        return out;
    }
}
