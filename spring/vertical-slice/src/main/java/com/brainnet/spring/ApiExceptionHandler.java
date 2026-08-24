package com.brainnet.spring;

import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import java.util.Map;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.http.converter.HttpMessageNotReadableException;

@RestControllerAdvice
class ApiExceptionHandler {
    private static final Logger logger = LoggerFactory.getLogger(ApiExceptionHandler.class);

    static final class ApiException extends RuntimeException {
        final HttpStatus status;
        final String code;

        ApiException(HttpStatus status, String code, String message) {
            super(message);
            this.status = status;
            this.code = code;
        }
    }

    private String trace(HttpServletRequest request) {
        return TraceFilter.traceId(request);
    }

    @ExceptionHandler(ApiException.class)
    ResponseEntity<?> api(ApiException ex, HttpServletRequest request) {
        if (ex.status == HttpStatus.UNPROCESSABLE_ENTITY && "VALIDATION_ERROR".equals(ex.code)) {
            return validationResponse(ex.getMessage(), request);
        }
        return response(ex.status, ex.code, ex.getMessage(), trace(request));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<?> validation(MethodArgumentNotValidException ex, HttpServletRequest request) {
        String traceId = trace(request);
        logger.warn("request_error status=422 code=VALIDATION_ERROR trace_id={}", traceId);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .header("X-Trace-Id", traceId)
                .body(new ApiModels.ValidationErrorView(
                        "VALIDATION_ERROR",
                        "Request validation failed",
                        traceId,
                        List.of(Map.of("type", "value_error", "loc", List.of("body"), "msg", "Request validation failed"))));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<?> unreadable(HttpMessageNotReadableException ex, HttpServletRequest request) {
        String traceId = trace(request);
        logger.warn("request_error status=422 code=VALIDATION_ERROR trace_id={}", traceId);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .header("X-Trace-Id", traceId)
                .body(new ApiModels.ValidationErrorView(
                        "VALIDATION_ERROR",
                        "Request validation failed",
                        traceId,
                        List.of(Map.of("type", "value_error", "loc", List.of("body"), "msg", "Request validation failed"))));
    }

    @ExceptionHandler(DataAccessException.class)
    ResponseEntity<ApiModels.ErrorView> database(DataAccessException ex, HttpServletRequest request) {
        String traceId = trace(request);
        logger.error("request_error status=500 code=DB_ERROR trace_id={} exception_type={}",
                traceId, ex.getClass().getSimpleName());
        return response(HttpStatus.INTERNAL_SERVER_ERROR, "DB_ERROR", "database operation failed", traceId);
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<ApiModels.ErrorView> unexpected(Exception ex, HttpServletRequest request) {
        String traceId = trace(request);
        logger.error("request_error status=500 code=INTERNAL_ERROR trace_id={} exception_type={}",
                traceId, ex.getClass().getSimpleName());
        return response(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Internal server error", traceId);
    }

    private ResponseEntity<ApiModels.ErrorView> response(HttpStatus status, String code, String message, String traceId) {
        if (status.value() < 500) {
            logger.warn("request_error status={} code={} trace_id={}", status.value(), code, traceId);
        }
        return ResponseEntity.status(status)
                .header("X-Trace-Id", traceId)
                .body(new ApiModels.ErrorView(code, message, traceId));
    }

    private ResponseEntity<ApiModels.ValidationErrorView> validationResponse(String message, HttpServletRequest request) {
        String traceId = trace(request);
        logger.warn("request_error status=422 code=VALIDATION_ERROR trace_id={}", traceId);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .header("X-Trace-Id", traceId)
                .body(new ApiModels.ValidationErrorView(
                        "VALIDATION_ERROR", message, traceId,
                        List.of(Map.of("type", "value_error", "loc", List.of("body"), "msg", message))));
    }
}
