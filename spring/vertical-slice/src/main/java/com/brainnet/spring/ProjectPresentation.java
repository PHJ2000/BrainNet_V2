package com.brainnet.spring;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
class ProjectPresentation {
    final WorkspaceRepository repository;
    final boolean ai;

    ProjectPresentation(WorkspaceRepository repository, @Value("${OPENAI_API_KEY:}") String key) {
        this.repository = repository;
        this.ai = !key.isBlank();
    }

    WorkspaceViews.Project view(ApiModels.ProjectView project, long uid) {
        String role =
                repository.db.queryForObject(
                        "SELECT role::text FROM project_user_role WHERE project_id=? AND user_id=?",
                        String.class,
                        project.id(),
                        uid);
        return new WorkspaceViews.Project(
                project.id(),
                project.name(),
                project.description(),
                project.owner_id(),
                project.created_at(),
                project.updated_at(),
                project.is_deleted(),
                project.member_count(),
                project.node_count(),
                project.tag_count(),
                role,
                ai);
    }

    String graphEtag(long projectId, List<ApiModels.NodeView> nodes) {
        return "\""
                + repository.hash(
                        List.of(
                                nodes,
                                repository.rows(
                                        "SELECT id,name,color FROM tag WHERE project_id=? ORDER BY"
                                                + " id",
                                        projectId)))
                + "\"";
    }
}
