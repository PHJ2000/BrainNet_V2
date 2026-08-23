package com.brainnet.benchmark;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class BenchmarkController {
    private final JdbcTemplate jdbcTemplate;
    private final boolean virtualThreads;

    public BenchmarkController(
            JdbcTemplate jdbcTemplate,
            @Value("${spring.threads.virtual.enabled:false}") boolean virtualThreads) {
        this.jdbcTemplate = jdbcTemplate;
        this.virtualThreads = virtualThreads;
    }

    @GetMapping("/health")
    Map<String, Object> health() {
        return Map.of(
                "status", "ok",
                "runtime", "spring",
                "virtual_threads", virtualThreads,
                "request_thread_virtual", Thread.currentThread().isVirtual());
    }

    @GetMapping("/io")
    Map<String, Object> ioWait(
            @RequestParam(name = "delay_ms", defaultValue = "200") int delayMs)
            throws InterruptedException {
        checkedDelay(delayMs, 2_000);
        Thread.sleep(delayMs);
        return Map.of("kind", "io", "delay_ms", delayMs);
    }

    @GetMapping("/db")
    Map<String, Object> dbWait(
            @RequestParam(name = "delay_ms", defaultValue = "50") int delayMs) {
        checkedDelay(delayMs, 1_000);
        double delaySeconds = delayMs / 1_000.0;
        Integer value = jdbcTemplate.queryForObject(
                "SELECT 1 FROM pg_sleep(?)", Integer.class, delaySeconds);
        return Map.of("kind", "db", "delay_ms", delayMs, "value", value);
    }

    @PostMapping("/roots/{projectId}")
    ResponseEntity<Map<String, Object>> createRoot(@PathVariable long projectId) {
        int rows = jdbcTemplate.update(
                """
                INSERT INTO benchmark_root(project_id, content)
                VALUES (?, 'root')
                ON CONFLICT (project_id) DO NOTHING
                """,
                projectId);
        if (rows == 0) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("created", false, "project_id", projectId));
        }
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(Map.of("created", true, "project_id", projectId));
    }

    private static void checkedDelay(int delayMs, int maximum) {
        if (delayMs < 0 || delayMs > maximum) {
            throw new IllegalArgumentException(
                    "delay_ms must be between 0 and " + maximum);
        }
    }
}
