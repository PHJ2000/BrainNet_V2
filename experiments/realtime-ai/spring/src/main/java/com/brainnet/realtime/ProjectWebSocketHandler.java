package com.brainnet.realtime;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class ProjectWebSocketHandler extends TextWebSocketHandler {
    private final ConcurrentHashMap<String, Set<WebSocketSession>> rooms = new ConcurrentHashMap<>();

    private String project(WebSocketSession session) {
        Object value = session.getAttributes().get("projectId");
        return value == null ? "unknown" : value.toString();
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        rooms.computeIfAbsent(project(session), ignored -> ConcurrentHashMap.newKeySet()).add(session);
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) throws IOException {
        synchronized (session) {
            session.sendMessage(message);
        }
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        Set<WebSocketSession> connections = rooms.get(project(session));
        if (connections != null) connections.remove(session);
    }

    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) throws Exception {
        afterConnectionClosed(session, CloseStatus.SERVER_ERROR);
        if (session.isOpen()) session.close(CloseStatus.SERVER_ERROR);
    }

    public int broadcast(String projectId, String payload) {
        Set<WebSocketSession> connections = rooms.getOrDefault(projectId, Set.of());
        int delivered = 0;
        for (WebSocketSession session : connections.toArray(WebSocketSession[]::new)) {
            try {
                synchronized (session) {
                    if (session.isOpen()) {
                        session.sendMessage(new TextMessage(payload));
                        delivered++;
                    }
                }
            } catch (IOException exception) {
                connections.remove(session);
            }
        }
        return delivered;
    }

    public int connectionCount() {
        return rooms.values().stream().mapToInt(Set::size).sum();
    }
}
