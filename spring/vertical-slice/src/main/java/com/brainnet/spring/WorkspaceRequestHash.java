package com.brainnet.spring;

import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;
import java.util.stream.Collectors;

/** Accepts persisted Python fingerprints during adoption without weakening command identity. */
record WorkspaceRequestHash(String current, String legacy) {
    boolean matches(Object stored) {
        return current.equals(stored) || legacy.equals(stored);
    }

    static String legacy(ObjectMapper json, Object value) {
        return digest(pythonJson(json, value));
    }

    static String digest(String value) {
        try {
            return HexFormat.of()
                    .formatHex(
                            MessageDigest.getInstance("SHA-256")
                                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }

    // V3 uses json.dumps(sort_keys=True, ensure_ascii=False), including default separators.
    private static String pythonJson(ObjectMapper json, Object value) {
        if (value instanceof Map<?, ?> object) {
            var sorted = new TreeMap<String, Object>();
            object.forEach((key, item) -> sorted.put(key.toString(), item));
            return sorted.entrySet().stream()
                    .map(entry -> quote(entry.getKey()) + ": " + pythonJson(json, entry.getValue()))
                    .collect(Collectors.joining(", ", "{", "}"));
        }
        if (value instanceof List<?> items) {
            return items.stream()
                    .map(item -> pythonJson(json, item))
                    .collect(Collectors.joining(", ", "[", "]"));
        }
        return value instanceof String text ? quote(text) : json.writeValueAsString(value);
    }

    private static String quote(String value) {
        var result = new StringBuilder();
        result.append('"');
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '"' -> result.append('\\').append('"');
                case '\\' -> result.append('\\').append('\\');
                case '\b' -> result.append('\\').append('b');
                case '\f' -> result.append('\\').append('f');
                case '\n' -> result.append('\\').append('n');
                case '\r' -> result.append('\\').append('r');
                case '\t' -> result.append('\\').append('t');
                default -> {
                    if (character < 0x20)
                        result.append('\\').append(String.format("u%04x", (int) character));
                    else result.append(character);
                }
            }
        }
        return result.append('"').toString();
    }
}
