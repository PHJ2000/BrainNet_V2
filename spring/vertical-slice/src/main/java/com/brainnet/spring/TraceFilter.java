package com.brainnet.spring;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import java.util.regex.Pattern;
import org.slf4j.MDC;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
class TraceFilter extends OncePerRequestFilter {
    static final String ATTRIBUTE = "traceId";
    private static final Pattern TRACE_ID = Pattern.compile("^[A-Za-z0-9._:-]{1,128}$");
    private static final Logger logger = LoggerFactory.getLogger(TraceFilter.class);

    static String traceId(HttpServletRequest request) {
        Object value = request.getAttribute(ATTRIBUTE);
        return value == null ? UUID.randomUUID().toString() : value.toString();
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String supplied = request.getHeader("X-Trace-Id");
        String traceId = supplied != null && TRACE_ID.matcher(supplied).matches()
                ? supplied : UUID.randomUUID().toString();
        request.setAttribute(ATTRIBUTE, traceId);
        response.setHeader("X-Trace-Id", traceId);
        MDC.put("traceId", traceId);
        try {
            chain.doFilter(request, response);
        } finally {
            logger.info("request_complete trace_id={} method={} path={} status={}",
                    traceId, request.getMethod(), request.getRequestURI(), response.getStatus());
            MDC.remove("traceId");
        }
    }
}
