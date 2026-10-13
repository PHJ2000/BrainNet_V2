package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceCommands.*;
import static com.brainnet.spring.WorkspaceInput.*;
import static com.brainnet.spring.WorkspaceViews.*;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;

@Service
class WorkspaceAssetService {
    private final ProjectAccessService access;

    final WorkspaceRepository repository;
    final WorkspaceBackupService files;

    WorkspaceAssetService(
            ProjectAccessService access,
            WorkspaceRepository repository,
            WorkspaceBackupService files) {
        this.access = access;

        this.repository = repository;
        this.files = files;
    }

    Asset view(Map<String, Object> row) {
        return new Asset(
                str(row.get("id")),
                str(row.get("name")),
                str(row.get("kind")),
                str(row.get("created_at")),
                "SEARCH".equals(row.get("kind"))
                        ? repository.view(row.get("payload"), Search.class)
                        : null);
    }

    List<Asset> list(long uid, String kind) {
        choice(Map.of("kind", kind), "kind", null, "SEARCH", "TEMPLATE");
        return repository
                .rows(
                        "SELECT * FROM personal_asset WHERE user_id=? AND kind=? ORDER BY"
                                + " created_at DESC",
                        uid,
                        kind)
                .stream()
                .map(this::view)
                .toList();
    }

    @Transactional
    public Asset create(long uid, AssetCreate command) {
        String id = command.id(), kind = command.kind(), name = command.name(), q = command.q();
        Long pid = command.project_id();
        var hash = repository.requestHash(command);
        if (repository.one("SELECT id FROM app_user WHERE id=? FOR UPDATE", uid) == null)
            throw fail(401, "UNAUTHORIZED", "Account no longer exists");
        var old = repository.one("SELECT * FROM personal_asset WHERE id=?", id);
        if (old != null) {
            if (number(old.get("user_id")) != uid || !hash.matches(old.get("request_hash")))
                throw fail(409, "REQUEST_ID_REUSED", "ID belongs to another request");
            return view(old);
        }
        if (repository.db.queryForObject(
                        "SELECT count(*) FROM personal_asset WHERE user_id=? AND kind=?",
                        Long.class,
                        uid,
                        kind)
                >= 30) throw fail(422, "ASSET_LIMIT", "Keep at most 30 items per kind");
        if (repository.one(
                        "SELECT id FROM personal_asset WHERE user_id=? AND kind=? AND name=?",
                        uid,
                        kind,
                        name)
                != null) throw fail(409, "ASSET_NAME_USED", "Name already used");
        Object payload;
        if (kind.equals("TEMPLATE")) {
            if (pid == null) throw fail(422, "PROJECT_REQUIRED", "Source project required");
            access.lock(pid, uid, false);
            payload = files.export(pid, uid, true);
            if (repository.encode(payload).getBytes(java.nio.charset.StandardCharsets.UTF_8).length
                    > 1024 * 1024) throw fail(413, "TEMPLATE_TOO_LARGE", "Template exceeds 1 MiB");
        } else {
            if (pid != null) access.member(pid, uid);
            payload = new Search(q, pid, command.bookmarked());
        }
        repository.db.update(
                "INSERT INTO personal_asset(id,user_id,kind,name,payload,request_hash,created_at)"
                        + " VALUES(?,?,?,?,?::jsonb,?,now())",
                id,
                uid,
                kind,
                name,
                repository.encode(payload),
                hash.current());
        return view(repository.one("SELECT * FROM personal_asset WHERE id=?", id));
    }

    Map<String, Object> owned(long uid, String id) {
        var row =
                repository.one(
                        "SELECT * FROM personal_asset WHERE user_id=? AND id=?", uid, uuid(id));
        if (row == null) throw fail(404, "ASSET_NOT_FOUND", "Saved item not found");
        return row;
    }

    @Transactional
    public void delete(long uid, String id) {
        owned(uid, id);
        repository.db.update("DELETE FROM personal_asset WHERE user_id=? AND id=?", uid, id);
    }

    ImportedProject instantiate(long uid, String id, String key) {
        var row = owned(uid, id);
        if (!"TEMPLATE".equals(row.get("kind")))
            throw fail(404, "ASSET_NOT_FOUND", "Template not found");
        return files.restore(uid, key, WorkspaceInput.map(row.get("payload")));
    }
}
