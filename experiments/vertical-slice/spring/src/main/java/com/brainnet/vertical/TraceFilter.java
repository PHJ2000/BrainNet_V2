package com.brainnet.vertical;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
class TraceFilter extends OncePerRequestFilter {
    static final String ATTRIBUTE = "traceId";

    @Override protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                             FilterChain chain) throws ServletException, IOException {
        String supplied = request.getHeader("X-Trace-Id");
        String traceId = supplied == null || supplied.isBlank() ? UUID.randomUUID().toString() : supplied;
        long started = System.nanoTime();
        request.setAttribute(ATTRIBUTE, traceId);
        response.setHeader("X-Trace-Id", traceId);
        MDC.put("traceId", traceId);
        try {
            chain.doFilter(request, response);
        } finally {
            double duration = (System.nanoTime() - started) / 1_000_000.0;
            if (supplied != null && !supplied.isBlank()) {
                System.out.printf("{\"level\":\"INFO\",\"trace_id\":\"%s\",\"method\":\"%s\",\"path\":\"%s\",\"status\":%d,\"duration_ms\":%.3f}%n",
                        traceId, request.getMethod(), request.getRequestURI(), response.getStatus(), duration);
            }
            MDC.remove("traceId");
        }
    }
}
