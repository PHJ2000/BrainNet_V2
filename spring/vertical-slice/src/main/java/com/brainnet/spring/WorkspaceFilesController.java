package com.brainnet.spring;

import static com.brainnet.spring.WorkspaceInput.*;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

import java.io.*;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.*;

@RestController
class WorkspaceFilesController {
    final WorkspaceBackupService files;

    WorkspaceFilesController(WorkspaceBackupService files) {
        this.files = files;
    }

    Map<String, Object> read(HttpServletRequest request) throws IOException {
        if (request.getContentLengthLong() > WorkspaceBackupService.MAX_BYTES)
            throw fail(413, "BACKUP_TOO_LARGE", "File exceeds 10 MiB");
        return files.parse(
                request.getInputStream().readNBytes(WorkspaceBackupService.MAX_BYTES + 1));
    }

    @PostMapping("/projects/import/preview")
    WorkspaceViews.BackupPreview preview(
            HttpServletRequest request, @RequestAttribute(JwtAuthFilter.USER_ID) long uid)
            throws IOException {
        return files.preview(read(request));
    }

    @PostMapping("/projects/import")
    @ResponseStatus(HttpStatus.CREATED)
    WorkspaceViews.ImportedProject restore(
            HttpServletRequest request,
            @RequestHeader("Idempotency-Key") String key,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid)
            throws IOException {
        return files.restore(uid, key, read(request));
    }

    @org.springframework.transaction.annotation.Transactional(
            isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ,
            readOnly = true)
    @GetMapping("/projects/{pid}/export/{format}")
    ResponseEntity<String> export(
            @PathVariable long pid,
            @PathVariable String format,
            @RequestAttribute(JwtAuthFilter.USER_ID) long uid,
            @RequestParam(required = false) Long root_id,
            @RequestParam(defaultValue = "false") boolean include_inactive) {
        if (!Set.of("json", "workspace", "markdown").contains(format))
            throw fail(404, "NOT_FOUND", "Unknown export format");
        var data = files.export(pid, uid, format.equals("workspace"));
        var graph = files.graph(data);
        String extension = format.equals("markdown") ? "md" : "json";
        String name =
                str(WorkspaceInput.map(graph.get("project")).get("name"))
                        .replaceAll("[<>:\"/\\\\|?*\\x00-\\x1f]", "_")
                        .strip()
                        .replaceAll("[ .]+$", "");
        if (name.isBlank()) name = "BrainNet";
        if (name.matches("(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\\..*)?")) name = "_" + name;
        name = name.substring(0, Math.min(80, name.length())) + "." + extension;
        String body =
                format.equals("markdown")
                        ? markdown(graph, pid, root_id, include_inactive)
                        : files.encode(data);
        return ResponseEntity.ok()
                .header(
                        "Content-Disposition",
                        "attachment; filename=brainnet."
                                + extension
                                + "; filename*=UTF-8''"
                                + URLEncoder.encode(name, StandardCharsets.UTF_8)
                                        .replace("+", "%20"))
                .header("Cache-Control", "no-store")
                .header("Access-Control-Expose-Headers", "Content-Disposition")
                .contentType(
                        MediaType.parseMediaType(
                                format.equals("markdown")
                                        ? "text/markdown;charset=UTF-8"
                                        : "application/json"))
                .body(body);
    }

    static String escape(String text) {
        return text.replaceAll("[\\r\\n]", " ")
                .replaceAll("([\\\\`*_{}\\[\\]()<>#+.!|~\\-])", "\\\\$1");
    }

    static String fence(String text, String indent) {
        int longest = 2;
        var m = java.util.regex.Pattern.compile("`+").matcher(text);
        while (m.find()) longest = Math.max(longest, m.group().length());
        String f = "`".repeat(longest + 1);
        return indent
                + f
                + "text\n"
                + indent
                + text.replace("\n", "\n" + indent)
                + "\n"
                + indent
                + f
                + "\n\n";
    }

    String markdown(Map<String, Object> g, long pid, Long root, boolean inactive) {
        var nodes = WorkspaceBackupService.list(g, "nodes", 5000);
        var byRef = WorkspaceBackupService.indexed(nodes, false);
        String rootRef = null;
        // Export traversal maps database IDs in the same deterministic order as the snapshot.
        if (root != null) {
            var raw = files.orderedNodes(pid);
            for (int i = 0; i < raw.size(); i++)
                if (number(raw.get(i).get("id")) == root) rootRef = "n" + (i + 1);
            if (rootRef == null) throw fail(404, "NODE_NOT_FOUND", "Selected branch not found");
        }
        var scope = new HashSet<String>();
        for (var n : nodes)
            if (root == null
                    || str(n.get("ref")).equals(rootRef)
                    || scope.contains(str(n.get("parent_ref")))) scope.add(str(n.get("ref")));
        var included = new HashSet<String>();
        for (var n : nodes)
            if (scope.contains(str(n.get("ref"))) && (inactive || "ACTIVE".equals(n.get("state"))))
                included.add(str(n.get("ref")));
        var context = new HashSet<String>();
        for (String ref : included) {
            Object parent = byRef.get(ref).get("parent_ref");
            while (parent != null && scope.contains(str(parent))) {
                if (!included.contains(str(parent))) context.add(str(parent));
                parent = byRef.get(parent).get("parent_ref");
            }
        }
        var tags =
                WorkspaceBackupService.indexed(WorkspaceBackupService.list(g, "tags", 5000), false);
        var attached = new HashMap<String, List<String>>();
        for (var l : WorkspaceBackupService.list(g, "node_tags", 50000))
            attached.computeIfAbsent(str(l.get("node_ref")), k -> new ArrayList<>())
                    .add(str(tags.get(l.get("tag_ref")).get("name")));
        var p = WorkspaceInput.map(g.get("project"));
        var out =
                new StringBuilder(
                        "# "
                                + escape(str(p.get("name")))
                                + "\n\n내보낸 시각: "
                                + g.get("exported_at")
                                + "\n범위: "
                                + (root == null ? "전체 프로젝트" : "노드 " + root + "와 모든 자손")
                                + "\n상태: "
                                + (inactive
                                        ? "ACTIVE / GHOST / ARCHIVED"
                                        : "ACTIVE (나머지 조상은 맥락 표시)")
                                + "\n\n원문은 text 코드 블록에 보존됩니다. 맥락 조상은 관계 표시용입니다.\n\n");
        if (p.get("description") != null)
            out.append("## 프로젝트 설명\n\n").append(fence(str(p.get("description")), ""));
        long base = rootRef == null ? 0 : number(byRef.get(rootRef).get("depth"));
        for (var n : nodes) {
            String ref = str(n.get("ref"));
            if (!included.contains(ref) && !context.contains(ref)) continue;
            int depth = (int) (number(n.get("depth")) - base);
            String indent = depth < 5 ? "" : "  ".repeat(depth - 4);
            String title = "노드 " + ref + (context.contains(ref) ? " · 맥락 조상" : "");
            out.append(depth < 5 ? "#".repeat(depth + 2) + " " : "  ".repeat(depth - 5) + "- ")
                    .append(title)
                    .append("\n\n")
                    .append(indent)
                    .append("상태: ")
                    .append(n.get("state"))
                    .append(" · 부모: ")
                    .append(n.get("parent_ref") == null ? "없음" : n.get("parent_ref"))
                    .append("\n")
                    .append(indent)
                    .append("태그: ")
                    .append(
                            String.join(
                                    ", ",
                                    attached.getOrDefault(ref, List.of("없음")).stream()
                                            .map(WorkspaceFilesController::escape)
                                            .toList()))
                    .append("\n\n");
            if (included.contains(ref)) out.append(fence(str(n.get("content")), indent));
        }
        if (included.isEmpty()) out.append("내보내기 조건에 맞는 노드가 없습니다.\n");
        return out.toString();
    }
}
