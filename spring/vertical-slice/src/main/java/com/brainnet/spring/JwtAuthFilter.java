package com.brainnet.spring;

import tools.jackson.databind.ObjectMapper;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.crypto.MACVerifier;
import com.nimbusds.jwt.SignedJWT;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
class JwtAuthFilter extends OncePerRequestFilter {
    static final String USER_ID = "userId";
    private final byte[] secret;
    private final ObjectMapper mapper;

    JwtAuthFilter(@Value("${JWT_SECRET:}") String secret, ObjectMapper mapper) {
        if (secret == null || secret.getBytes(StandardCharsets.UTF_8).length < 32) {
            throw new IllegalStateException("JWT_SECRET must be at least 32 bytes");
        }
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
        this.mapper = mapper;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return request.getRequestURI().equals("/health");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String traceId = TraceFilter.traceId(request);
        String header = request.getHeader("Authorization");
        try {
            if (header == null || !header.startsWith("Bearer ")) {
                throw new IllegalArgumentException("missing bearer token");
            }
            SignedJWT jwt = SignedJWT.parse(header.substring("Bearer ".length()));
            if (!JWSAlgorithm.HS256.equals(jwt.getHeader().getAlgorithm())
                    || !jwt.verify(new MACVerifier(secret))) {
                throw new IllegalArgumentException("invalid signature");
            }
            Date expiration = jwt.getJWTClaimsSet().getExpirationTime();
            String subject = jwt.getJWTClaimsSet().getSubject();
            if (expiration == null || expiration.before(new Date())
                    || subject == null || !subject.matches("[1-9][0-9]*")) {
                throw new IllegalArgumentException("invalid claims");
            }
            request.setAttribute(USER_ID, Long.parseLong(subject));
        } catch (Exception ex) {
            response.setHeader("WWW-Authenticate", "Bearer");
            String message = header == null ? "Not authenticated" : "Could not validate credentials";
            ApiErrorWriter.write(mapper, response, 401, "UNAUTHORIZED", message, traceId);
            return;
        }
        chain.doFilter(request, response);
    }
}
