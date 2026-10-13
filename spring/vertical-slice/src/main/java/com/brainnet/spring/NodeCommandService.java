package com.brainnet.spring;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;

@Service
class NodeCommandService {
    private final ProjectAccessService access;

    final VerticalService nodes;
    final NodeOperationService operations;
    final WorkspaceRepository repository;

    NodeCommandService(
            ProjectAccessService access,
            VerticalService nodes,
            NodeOperationService operations,
            WorkspaceRepository repository) {
        this.access = access;

        this.nodes = nodes;
        this.operations = operations;
        this.repository = repository;
    }

    @Transactional
    public ApiModels.NodeView patch(
            long pid, long uid, long node, ApiModels.NodePatch body, String key) {
        access.editor(pid, uid);
        var request = List.of("update", node, repository.json.convertValue(body, Map.class));
        var old = operations.replay(pid, uid, key, request);
        if (old != null)
            return repository.json.convertValue(old.response(), ApiModels.NodeView.class);
        var result = nodes.patchNode(pid, node, body, uid);
        operations.savePatchReceipt(pid, uid, node, key, request, result);
        return result;
    }
}
