package com.brainnet.realtime;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;

@Component
public class ProviderClient {
    private final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(1))
            .version(HttpClient.Version.HTTP_1_1)
            .build();
    private final ObjectMapper mapper = new ObjectMapper();
    private final String providerUrl;
    private final Duration timeout;

    public ProviderClient(@Value("${PROVIDER_URL:http://provider:8080}") String providerUrl,
                          @Value("${UPSTREAM_TIMEOUT_MS:1000}") long timeoutMs) {
        this.providerUrl = providerUrl;
        this.timeout = Duration.ofMillis(timeoutMs);
    }

    public Map<String, Object> generate(Map<String, Object> body) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(URI.create(providerUrl + "/generate"))
                .timeout(timeout)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(mapper.writeValueAsBytes(body)))
                .build();
        HttpResponse<byte[]> response = client.send(request, HttpResponse.BodyHandlers.ofByteArray());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new UpstreamException(response.statusCode());
        }
        return mapper.readValue(response.body(), new TypeReference<>() {});
    }

    public HttpResponse<InputStream> stream(int delayMs, int intervalMs, int chunks)
            throws IOException, InterruptedException {
        String query = "?delay_ms=" + delayMs + "&interval_ms=" + intervalMs + "&chunks=" + chunks;
        HttpRequest request = HttpRequest.newBuilder(URI.create(providerUrl + "/stream" + query))
                .timeout(Duration.ofSeconds(30))
                .GET()
                .build();
        HttpResponse<InputStream> response = client.send(request, HttpResponse.BodyHandlers.ofInputStream());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            response.body().close();
            throw new UpstreamException(response.statusCode());
        }
        return response;
    }

    static class UpstreamException extends IOException {
        UpstreamException(int status) { super("upstream status " + status); }
    }
}
