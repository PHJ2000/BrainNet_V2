package com.brainnet.spring;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.http.converter.HttpMessageNotReadableException;

@RestControllerAdvice
class ApiExceptionHandler {
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
    ResponseEntity<ApiModels.ErrorView> api(ApiException ex, HttpServletRequest request) {
        return response(ex.status, ex.code, ex.getMessage(), trace(request));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<ApiModels.ErrorView> validation(MethodArgumentNotValidException ex, HttpServletRequest request) {
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Request validation failed", trace(request));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<ApiModels.ErrorView> unreadable(HttpMessageNotReadableException ex, HttpServletRequest request) {
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Request validation failed", trace(request));
    }

    @ExceptionHandler(DataAccessException.class)
    ResponseEntity<ApiModels.ErrorView> database(DataAccessException ex, HttpServletRequest request) {
        return response(HttpStatus.INTERNAL_SERVER_ERROR, "DB_ERROR", "database operation failed", trace(request));
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<ApiModels.ErrorView> unexpected(Exception ex, HttpServletRequest request) {
        return response(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Internal server error", trace(request));
    }

    private ResponseEntity<ApiModels.ErrorView> response(HttpStatus status, String code, String message, String traceId) {
        return ResponseEntity.status(status)
                .header("X-Trace-Id", traceId)
                .body(new ApiModels.ErrorView(code, message, traceId));
    }
}
