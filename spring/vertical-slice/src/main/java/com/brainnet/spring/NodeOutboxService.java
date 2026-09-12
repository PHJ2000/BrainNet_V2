package com.brainnet.spring;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/** Caller owns the transaction containing both the mutation and its event. */
@Service
class NodeOutboxService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    NodeOutboxService(JdbcTemplate jdbc, ObjectMapper mapper) { this.jdbc=jdbc; this.mapper=mapper; }

    void append(long projectId, long nodeId, String type, Map<String, Object> extra) {
        String eventId=UUID.randomUUID().toString();
        var payload=new LinkedHashMap<String,Object>(extra);
        payload.put("event_id",eventId); payload.put("project_id",projectId); payload.put("node_id",nodeId);
        jdbc.update("INSERT INTO outbox_event(event_id,aggregate_type,aggregate_id,event_type,payload,occurred_at) "
                + "VALUES (?,'node',?,?,?::jsonb,now())",eventId,nodeId,type,mapper.writeValueAsString(payload));
    }
}
