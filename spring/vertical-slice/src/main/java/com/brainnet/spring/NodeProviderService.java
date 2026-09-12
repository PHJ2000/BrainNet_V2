package com.brainnet.spring;
import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import java.io.IOException;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Service
class NodeProviderService {
    private final ObjectMapper mapper;
    private final HttpClient aiHttp;
    private final String aiUrl;
    private final String aiKey;
    private final String aiModel;
    private final long aiTimeoutSeconds;
    NodeProviderService(ObjectMapper mapper,
            @Value("${OPENAI_API_URL:https://api.openai.com/v1/chat/completions}") String aiUrl,
            @Value("${OPENAI_API_KEY:}") String aiKey,
            @Value("${OPENAI_MODEL:gpt-3.5-turbo}") String aiModel,
            @Value("${OPENAI_TIMEOUT_SECONDS:30}") long aiTimeoutSeconds) {
        this.mapper=mapper; this.aiUrl=aiUrl; this.aiKey=aiKey; this.aiModel=aiModel;
        this.aiTimeoutSeconds=Math.max(1,aiTimeoutSeconds);
        this.aiHttp=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(this.aiTimeoutSeconds)).build();
    }
    String generateContent(String prompt) {
        if (aiKey == null || aiKey.isBlank()) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "AI_PROVIDER_NOT_CONFIGURED",
                    "AI provider is not configured");
        }
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("model", aiModel);
            payload.put("messages", List.of(
                    Map.of("role", "system", "content", "당신은 창의적인 아이디어를 제공하는 도우미입니다."),
                    Map.of("role", "user", "content",
                            "다음 주제와 관련된 새로운 아이디어를 간략한 문장 형태로 한 개 작성해줘: " + prompt)));
            payload.put("max_tokens", 256);
            payload.put("temperature", 0.7);
            HttpRequest request = HttpRequest.newBuilder(URI.create(aiUrl))
                    .timeout(Duration.ofSeconds(aiTimeoutSeconds))
                    .header("Authorization", "Bearer " + aiKey)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(payload)))
                    .build();
            HttpResponse<String> response = aiHttp.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE",
                        "AI provider request failed");
            }
            JsonNode content = mapper.readTree(response.body()).path("choices").path(0).path("message").path("content");
            String answer = content.isString() ? content.asText() : null;
            if (answer == null || answer.isBlank()) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE",
                        "AI provider request failed");
            }
            String normalized = answer.strip().split("\\R", 2)[0].replaceFirst("^\\d+\\.\\s*", "").trim();
            if (normalized.isBlank()) throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE", "AI provider request failed");
            return normalized;
        } catch (HttpTimeoutException ex) {
            throw new ApiException(HttpStatus.GATEWAY_TIMEOUT, "AI_PROVIDER_TIMEOUT",
                    "AI provider request timed out");
        } catch (ApiException ex) {
            throw ex;
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE",
                    "AI provider request failed");
        } catch (IOException | RuntimeException ex) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PROVIDER_UNAVAILABLE",
                    "AI provider request failed");
        }
    }

}
