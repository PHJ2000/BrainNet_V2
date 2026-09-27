package com.brainnet.spring;

import static com.brainnet.spring.ApiExceptionHandler.ApiException;
import java.time.OffsetDateTime;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;

@Service
class InviteMailService {
    private final JavaMailSender sender;
    private final String from;

    InviteMailService(JavaMailSender sender, @Value("${INVITE_MAIL_FROM:brainnet@localhost}") String from) {
        this.sender = sender;
        this.from = from;
    }

    void send(String email, long projectId, String token, OffsetDateTime expiresAt) {
        var message = new SimpleMailMessage();
        message.setFrom(from);
        message.setTo(email);
        message.setSubject("BRAINNET project invitation");
        message.setText("You are invited to BRAINNET project " + projectId
                + ".\nSign in with " + email + " and submit this token to POST /projects/join."
                + "\nInvitation token: " + token + "\nExpires at: " + expiresAt
                + "\nThis invitation can be used once. A new invitation invalidates the previous token.");
        try {
            sender.send(message);
        } catch (MailException ex) {
            // Do not expose addresses, tokens, SMTP credentials or provider errors in logs/responses.
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "INVITE_DELIVERY_FAILED", "Invitation email could not be delivered");
        }
    }
}
