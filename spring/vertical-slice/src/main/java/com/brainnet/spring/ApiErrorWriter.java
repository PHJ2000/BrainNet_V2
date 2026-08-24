package com.brainnet.spring;

import tools.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;

final class ApiErrorWriter {
    private ApiErrorWriter() {}

    static void write(
            ObjectMapper mapper,
            HttpServletResponse response,
            int status,
            String code,
            String message,
            String traceId) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.setHeader("X-Trace-Id", traceId);
        mapper.writeValue(response.getOutputStream(), new ApiModels.ErrorView(code, message, traceId));
    }
}
