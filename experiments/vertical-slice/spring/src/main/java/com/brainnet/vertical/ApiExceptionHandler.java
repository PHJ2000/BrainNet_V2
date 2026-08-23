package com.brainnet.vertical;

import static com.brainnet.vertical.ApiModels.ErrorView;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
class ApiExceptionHandler {
    static final class ApiException extends RuntimeException {
        final HttpStatus status;
        final String code;
        ApiException(HttpStatus status, String code, String message) { super(message); this.status = status; this.code = code; }
    }

    private String trace(HttpServletRequest request) { return String.valueOf(request.getAttribute(TraceFilter.ATTRIBUTE)); }
    private ResponseEntity<ErrorView> response(HttpStatus status, String code, String message, HttpServletRequest request) {
        return ResponseEntity.status(status).body(new ErrorView(code, message, trace(request)));
    }

    @ExceptionHandler(ApiException.class)
    ResponseEntity<ErrorView> api(ApiException ex, HttpServletRequest request) {
        return response(ex.status, ex.code, ex.getMessage(), request);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<ErrorView> validation(MethodArgumentNotValidException ex, HttpServletRequest request) {
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", ex.getBindingResult().getAllErrors().getFirst().getDefaultMessage(), request);
    }

    @ExceptionHandler(DataAccessException.class)
    ResponseEntity<ErrorView> database(DataAccessException ex, HttpServletRequest request) {
        String trace = trace(request);
        System.out.printf("{\"level\":\"ERROR\",\"trace_id\":\"%s\",\"code\":\"DB_ERROR\",\"error\":\"%s\"}%n", trace, ex.getClass().getSimpleName());
        return response(HttpStatus.INTERNAL_SERVER_ERROR, "DB_ERROR", "database operation failed", request);
    }
}

