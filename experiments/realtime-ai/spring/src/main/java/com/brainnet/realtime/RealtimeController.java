package com.brainnet.realtime;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.InputStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Map;

@RestController
public class RealtimeController {
    private final ProviderClient provider;
    private final ProjectWebSocketHandler sockets;
    private final ObjectMapper mapper = new ObjectMapper();

    public RealtimeController(ProviderClient provider, ProjectWebSocketHandler sockets) {
        this.provider = provider;
        this.sockets = sockets;
    }

    @GetMapping("/health")
    public Map<String, String> health() { return Map.of("status", "ok", "mode", "spring"); }

    @GetMapping("/metrics")
    public Map<String, Integer> metrics() { return Map.of("websocket_connections", sockets.connectionCount()); }

    @PostMapping("/ai/generate")
    public ResponseEntity<?> generate(@RequestBody Map<String, Object> body) {
        try {
            return ResponseEntity.ok(provider.generate(body));
        } catch (HttpTimeoutException exception) {
            return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT).body(Map.of("detail", "upstream timeout"));
        } catch (ProviderClient.UpstreamException exception) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(Map.of("detail", "upstream failure"));
        } catch (Exception exception) {
            if (exception instanceof InterruptedException) Thread.currentThread().interrupt();
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(Map.of("detail", "upstream failure"));
        }
    }

    @GetMapping(value = "/ai/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public void stream(@RequestParam(defaultValue = "100") int delay_ms,
                       @RequestParam(defaultValue = "50") int interval_ms,
                       @RequestParam(defaultValue = "10") int chunks,
                       HttpServletResponse response) throws Exception {
        response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
        try (InputStream input = provider.stream(delay_ms, interval_ms, chunks).body();
             BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                response.getOutputStream().write((line + "\n").getBytes(StandardCharsets.UTF_8));
                if (line.isEmpty()) response.getOutputStream().flush();
            }
        }
    }

    @PostMapping("/projects/{projectId}/broadcast")
    public Map<String, Integer> broadcast(@PathVariable String projectId, @RequestBody Map<String, Object> body)
            throws Exception {
        return Map.of("delivered", sockets.broadcast(projectId, mapper.writeValueAsString(body)));
    }
}
