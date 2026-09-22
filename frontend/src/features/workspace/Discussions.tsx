"use client";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import ProjectDialog from "@/features/projects/ProjectDialog";
import { button, field, primary, useMembers, useWorkspaceList, workspaceError, type Discussion } from "./api";
import { useWorkspaceDraft } from "./useWorkspaceDraft";
import { ReplyThread } from "./Collaboration";
import CloudDraft from "./CloudDraft";

function Editor({ item, projectId, author, onClose }: { item: Discussion; projectId: number; author: boolean; onClose: () => void }) {
  const [body, setBody] = useState(item.body), [resolved, setResolved] = useState(item.resolved);
  const storage = useWorkspaceDraft<Discussion>(projectId, "discussion");
  const [busy, setBusy] = useState(false), [attempted, setAttempted] = useState(storage.draft?.item.id === item.id && storage.draft.attempted), [error, setError] = useState("");
  const [node, setNode] = useState(String(item.node_id ?? ""));
  const cache = useQueryClient(), isNew = item.version < 0;
  const { save: saveDraft } = storage;
  useEffect(() => { saveDraft({ item: { ...item, body, resolved, node_id: Number(node) || null }, attempted }); }, [item, body, resolved, node, attempted, saveDraft]);
  const save = async () => {
    setBusy(true); setAttempted(true); setError("");
    storage.save({ item: { ...item, body, resolved, node_id: Number(node) || null }, attempted: true });
    try {
      if (isNew) await apiClient.post(`/projects/${projectId}/discussions`, { id: item.id, body, node_id: Number(node) || null });
      else await apiClient.put(`/projects/${projectId}/discussions/${item.id}`, { body, resolved, expected_version: item.version });
      storage.discard(); await cache.invalidateQueries({ queryKey: ["workspace", projectId] }); onClose();
    } catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <ProjectDialog title={isNew ? "새 토론" : "토론 편집"} busy={busy} onClose={onClose}><form className="space-y-4" onSubmit={e => { e.preventDefault(); if (!busy) void save(); }}>
    <fieldset disabled={busy || (attempted && isNew)} className="space-y-4">
      <label className="block text-sm">토론 내용<textarea aria-label="토론 내용" readOnly={!author} className={field} required maxLength={8000} rows={6} value={body} onChange={e => setBody(e.target.value)} /></label>
      {isNew && <label className="block text-sm">연결할 노드 번호 · 선택<input type="number" min={1} className={field} value={node} onChange={e => setNode(e.target.value)} /></label>}
      {!isNew && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={resolved} onChange={e => setResolved(e.target.checked)} />해결한 토론</label>}
    </fieldset>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <button disabled={busy || !body.trim()} className={primary}>{busy ? "저장 중…" : error ? "같은 요청 재시도" : "토론 저장"}</button>
  </form></ProjectDialog>;
}

export default function Discussions({ projectId, readOnly, owner, initialThread }: { projectId: number; readOnly: boolean; owner: boolean; initialThread?: string | null }) {
  const [focus, setFocus] = useState(initialThread ?? "");
  const query = useWorkspaceList<Discussion>(projectId, "discussions", focus ? { thread_id: focus } : {}), members = useMembers(projectId);
  const me = useQuery({ queryKey: ["me"], queryFn: async () => (await apiClient.get<{id: number}>("/users/me")).data });
  const [editing, setEditing] = useState<Discussion | null>(null), [showResolved, setShowResolved] = useState(!!initialThread);
  const storage = useWorkspaceDraft<Discussion>(projectId, "discussion");
  const rows = query.data?.pages.flatMap(page => page.items) ?? [];
  return <section className="space-y-5" aria-label="프로젝트 토론">
    <header className="flex flex-wrap justify-between gap-3"><div><h2 className="text-xl font-semibold">함께 결정할 이야기</h2><p className="mt-1 text-sm text-slate-500">아이디어의 맥락과 결정을 남기세요. 내용 수정은 작성자만 할 수 있습니다.</p></div>{!readOnly && <button className={primary} disabled={!!storage.draft} onClick={() => setEditing({ id: uuid(), body: "", author_id: me.data?.id ?? null, node_id: null, resolved: false, version: -1, created_at: new Date().toISOString() })}>새 토론</button>}</header>
    {!readOnly && storage.draft && <div className="flex flex-wrap items-center gap-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm"><span>이 탭에 저장된 토론 초안이 있습니다.</span><button className={button} onClick={() => setEditing(storage.draft!.item)}>토론 초안 이어쓰기</button><button className="underline" onClick={storage.discard}>초안 폐기</button></div>}
    {!readOnly && <CloudDraft projectId={projectId} kind="discussion" />}
    {focus && <button className={button} onClick={() => setFocus("")}>프로젝트의 모든 토론 보기</button>}
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showResolved} onChange={e => setShowResolved(e.target.checked)} />해결한 토론도 보기</label>
    {query.isLoading && <p role="status">토론을 불러오는 중…</p>}
    {query.error ? <div role="alert">{workspaceError(query.error)} <button className={button} onClick={() => void query.refetch()}>다시 불러오기</button></div> : <ul className="divide-y border-y border-slate-200">{rows.filter(row => showResolved || !row.resolved).map(row => <li key={row.id} className="py-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500"><span>{members.data?.find(m => m.user_id === row.author_id)?.email ?? "이전 멤버"} · {new Date(row.created_at).toLocaleString("ko-KR")}{row.node_id && ` · 노드 #${row.node_id}`}</span><span>{row.resolved ? "해결됨" : "논의 중"}</span></div>
      <p className="whitespace-pre-wrap break-words text-sm leading-7">{row.body}</p>{!readOnly && (owner || me.data?.id === row.author_id) && <button disabled={!!storage.draft && storage.draft.item.id !== row.id} className="mt-3 text-sm text-indigo-700 underline disabled:opacity-40" onClick={() => setEditing(storage.draft?.item.id === row.id ? storage.draft.item : row)}>{me.data?.id === row.author_id ? "편집 / 해결" : "해결 상태 변경"}</button>}
      <ReplyThread projectId={projectId} discussionId={row.id} readOnly={readOnly} initiallyOpen={focus === row.id} />
    </li>)}</ul>}
    {!query.isLoading && !query.error && !rows.some(row => showResolved || !row.resolved) && <p className="py-8 text-center text-sm text-slate-500">표시할 토론이 없습니다.</p>}
    {query.hasNextPage && <button className={button} onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>이전 토론 더 보기</button>}
    {editing && <Editor key={editing.id} item={editing} projectId={projectId} author={editing.version < 0 || me.data?.id === editing.author_id} onClose={() => setEditing(null)} />}
  </section>;
}
