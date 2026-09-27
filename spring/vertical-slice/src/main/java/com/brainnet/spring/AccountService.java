package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import static com.brainnet.spring.VerticalService.timestamp;
import com.nimbusds.jose.*;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.*;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
class AccountService {
    record Register(@NotBlank @Email @Size(max = 120) String email, @NotNull String password, @Size(max = 80) String name) {}
    record User(long id, String email, String name, OffsetDateTime created_at, OffsetDateTime last_login_at) {}
    private final JdbcTemplate jdbc;
    private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(12);
    private final byte[] secret;
    private final long tokenMinutes;

    AccountService(JdbcTemplate jdbc, @Value("${JWT_SECRET}") String secret,
                   @Value("${ACCESS_TOKEN_EXPIRE_MINUTES:30}") long tokenMinutes) {
        this.jdbc = jdbc;
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
        this.tokenMinutes = tokenMinutes;
        if (tokenMinutes <= 0) throw new IllegalStateException("ACCESS_TOKEN_EXPIRE_MINUTES must be positive");
    }

    private User view(ResultSet rs, int row) throws SQLException {
        return new User(rs.getLong("id"), rs.getString("email"), rs.getString("name"), timestamp(rs, "created_at"), timestamp(rs, "last_login_at"));
    }

    User register(Register body) {
        // Passlib's bcrypt hashes are supported; bcrypt cannot safely distinguish passwords after 72 bytes.
        if (body.password().getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Password exceeds bcrypt's 72-byte limit");
        }
        String email = body.email();
        int at = email.lastIndexOf('@');
        email = email.substring(0, at + 1) + email.substring(at + 1).toLowerCase(Locale.ROOT);
        try {
            return jdbc.queryForObject("INSERT INTO app_user(email,name,pw_hash,created_at) VALUES (?,?,?,now()) RETURNING *",
                    this::view, email, body.name(), passwords.encode(body.password()));
        } catch (DuplicateKeyException ex) {
            throw new ApiException(HttpStatus.CONFLICT, "CONFLICT", "Email already registered");
        }
    }

    Map<String, String> login(String email, String password) {
        var users = jdbc.queryForList("SELECT id,pw_hash FROM app_user WHERE email=?", email);
        if (users.isEmpty() || !passwords.matches(password, (String) users.getFirst().get("pw_hash"))) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "UNAUTHORIZED", "Invalid credentials");
        }
        try {
            var jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), new JWTClaimsSet.Builder()
                    .subject(users.getFirst().get("id").toString())
                    .expirationTime(Date.from(Instant.now().plusSeconds(tokenMinutes * 60))).build());
            jwt.sign(new MACSigner(secret));
            return Map.of("access_token", jwt.serialize(), "token_type", "Bearer");
        } catch (JOSEException ex) {
            throw new IllegalStateException("Unable to sign access token", ex);
        }
    }

    User me(long userId) {
        var users = jdbc.query("SELECT * FROM app_user WHERE id=?", this::view, userId);
        if (users.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "User not found");
        return users.getFirst();
    }

    List<Map<String, Object>> summaries(long userId) {
        return jdbc.queryForList("SELECT t.project_id,t.id AS tag_id,t.name AS tag_name,'' AS summary,"
                + "count(n.id) FILTER (WHERE n.author_id=?) AS nodes_contributed "
                + "FROM tag t JOIN project_user_role m ON m.project_id=t.project_id AND m.user_id=? "
                + "LEFT JOIN tag_node tn ON tn.tag_id=t.id LEFT JOIN node n ON n.id=tn.node_id "
                + "GROUP BY t.id ORDER BY t.project_id,t.id", userId, userId);
    }
}
