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
        final List<Map<String, Object>> errors;

        ApiException(HttpStatus status, String code, String message) {
            this(status, code, message, null);
        }

        ApiException(HttpStatus status, String code, String message, List<Map<String, Object>> errors) {
            super(message);
            this.status = status;
            this.code = code;
            this.errors = errors;
        }
    }

    private String trace(HttpServletRequest request) {
        return TraceFilter.traceId(request);
    }

    @ExceptionHandler(ApiException.class)
    ResponseEntity<?> api(ApiException ex, HttpServletRequest request) {
        if (ex.status == HttpStatus.UNPROCESSABLE_ENTITY && "VALIDATION_ERROR".equals(ex.code)) {
            return validationResponse("Request validation failed", request, ex.errors);
        }
        if ("NODE_CREATION_BUSY".equals(ex.code)) {
            return ResponseEntity.status(ex.status).header("Retry-After", "1")
                    .header("X-Trace-Id", trace(request))
                    .body(new ApiModels.ErrorView(ex.code, ex.getMessage(), trace(request)));
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
                        defaultValidationErrors()));
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
                        defaultValidationErrors()));
    }

    @ExceptionHandler({org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class,
            org.springframework.web.bind.MissingServletRequestParameterException.class})
    ResponseEntity<?> invalidParameter(Exception ex, HttpServletRequest request) {
        return validationResponse("Request validation failed", request, null);
    }

    @ExceptionHandler(DataAccessException.class)
    ResponseEntity<ApiModels.ErrorView> database(DataAccessException ex, HttpServletRequest request) {
        String traceId = trace(request);
        logger.error("request_error status=500 code=DB_ERROR trace_id={} exception_type={}",
                traceId, ex.getClass().getSimpleName());
        return response(HttpStatus.INTERNAL_SERVER_ERROR, "DB_ERROR", "database operation failed", traceId);
    }

    @ExceptionHandler({org.springframework.web.HttpMediaTypeNotSupportedException.class,
            org.springframework.web.HttpRequestMethodNotSupportedException.class,
            org.springframework.web.servlet.resource.NoResourceFoundException.class})
    ResponseEntity<?> httpError(Exception ex, HttpServletRequest request) {
        var error = (org.springframework.web.ErrorResponse) ex;
        HttpStatus status = HttpStatus.valueOf(error.getStatusCode().value());
        return response(status, status == HttpStatus.NOT_FOUND ? "NOT_FOUND" : "HTTP_ERROR",
                status.getReasonPhrase(), trace(request));
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

    private ResponseEntity<ApiModels.ValidationErrorView> validationResponse(
            String message, HttpServletRequest request, List<Map<String, Object>> errors) {
        String traceId = trace(request);
        logger.warn("request_error status=422 code=VALIDATION_ERROR trace_id={}", traceId);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .header("X-Trace-Id", traceId)
                .body(new ApiModels.ValidationErrorView(
                        "VALIDATION_ERROR", message, traceId,
                        errors == null ? defaultValidationErrors() : errors));
    }

    private List<Map<String, Object>> defaultValidationErrors() {
        return List.of(Map.of(
                "type", "value_error",
                "loc", List.of("body"),
                "msg", "Request validation failed",
                "input", Map.of(),
                "ctx", Map.of("error", Map.of())));
    }
}
