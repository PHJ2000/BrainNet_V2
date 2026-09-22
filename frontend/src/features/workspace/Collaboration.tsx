"use client";
import { useState } from "react";
import Link from "next/link";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import ProjectDialog from "@/features/projects/ProjectDialog";
import { button, field, primary, useMembers, workspaceError, type Page, type Knowledge, type Task } from "./api";

type Reply = { id: string; author_id: number; body: string; mentions: number[]; created_at: string };
export function ReplyThread({ projectId, discussionId, readOnly, initiallyOpen = false }: { projectId: number; discussionId: string; readOnly: boolean; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen), [body, setBody] = useState(""), [mentions, setMentions] = useState<number[]>([]);
  const [pending, setPending] = useState<{ id: string; body: string; mentions: number[] } | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const members = useMembers(projectId), cache = useQueryClient(), url = `/projects/${projectId}/discussions/${discussionId}/replies`;
  const query = useInfiniteQuery({ queryKey: ["workspace", projectId, "replies", discussionId], initialPageParam: null as string | null, enabled: open,
    queryFn: async ({ pageParam, signal }) => (await apiClient.get<Page<Reply>>(url, { signal, params: { before: pageParam } })).data,
    getNextPageParam: page => page.next_cursor as string | undefined ?? undefined });
  const send = async () => {
    if (busy) return;
    const payload = pending ?? { id: uuid(), body, mentions };
    setPending(payload); setBusy(true); setError("");
    try { await apiClient.post(url, payload); setPending(null); setBody(""); setMentions([]); await cache.invalidateQueries({ queryKey: ["workspace", projectId] }); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <div className="mt-4 border-l-2 border-slate-200 pl-4"><button className={button} aria-expanded={open} onClick={() => setOpen(!open)}>답글 {open ? "접기" : "보기 / 작성"}</button>{open && <div className="mt-4 space-y-4">
    {query.error && <p role="alert">{workspaceError(query.error)}</p>}
    {query.data?.pages.flatMap(page => page.items).map(r => <article key={r.id} className="border-b border-slate-100 pb-3"><p className="text-xs text-slate-500">{members.data?.find(m => m.user_id === r.author_id)?.email ?? "이전 멤버"} · {new Date(r.created_at).toLocaleString("ko-KR")}</p><p className="mt-2 whitespace-pre-wrap break-words text-sm">{r.body}</p>{r.mentions.length > 0 && <p className="mt-2 text-xs text-indigo-700">알림: {r.mentions.map(id => members.data?.find(m => m.user_id === id)?.email ?? "이전 멤버").join(", ")}</p>}</article>)}
    {query.hasNextPage && <button className={button} onClick={() => void query.fetchNextPage()}>이전 답글</button>}
    {!readOnly && <form onSubmit={e => { e.preventDefault(); void send(); }} className="space-y-3"><fieldset disabled={busy || !!pending}><label className="block text-sm">답글 내용<textarea className={field} required maxLength={8000} rows={3} value={body} onChange={e => setBody(e.target.value)} /></label><label className="mt-3 block text-sm">알림 보낼 멤버 · 여러 명 선택 가능<select multiple aria-label="멘션할 멤버" className={field} value={mentions.map(String)} onChange={e => setMentions(Array.from(e.target.selectedOptions, o => Number(o.value)))}>{members.data?.map(m => <option key={m.user_id} value={m.user_id}>{m.email}</option>)}</select></label></fieldset>{error && <p role="alert">{error}</p>}<button className={primary} disabled={busy || !body.trim()}>{pending ? "같은 답글 재시도" : "답글 등록"}</button></form>}
  </div>}</div>;
}

type Notice = { id: number; project_id: number; discussion_id: string; project_name: string; preview: string; read: boolean };
export function Inbox() {
  const [unread, setUnread] = useState(true), [error, setError] = useState("");
  const query = useInfiniteQuery({ queryKey: ["inbox", unread], initialPageParam: null as number | null, refetchInterval: 30000,
    queryFn: async ({ pageParam, signal }) => (await apiClient.get<Page<Notice>>("/workspace/inbox", { signal, params: { before: pageParam, unread } })).data,
    getNextPageParam: page => page.next_cursor as number | undefined ?? undefined });
  const mark = async (id: number) => { try { await apiClient.put(`/workspace/inbox/${id}/read`); await query.refetch(); } catch (e) { setError(workspaceError(e)); } };
  return <section className="space-y-4" aria-label="알림함"><h2 className="text-xl font-semibold">나에게 온 이야기</h2><label className="flex gap-2 text-sm"><input type="checkbox" checked={unread} onChange={e => setUnread(e.target.checked)} />읽지 않은 알림만</label>{(error || query.error) && <p role="alert">{error || workspaceError(query.error)}</p>}{query.isLoading && <p role="status">알림을 불러오는 중…</p>}
    <ul className="divide-y">{query.data?.pages.flatMap(page => page.items).map(n => <li key={n.id} className="space-y-2 py-4"><Link className="font-medium text-indigo-700 underline" href={`/dashboard/projects/${n.project_id}?view=discussions&thread=${n.discussion_id}`}>{n.project_name}의 토론 열기</Link><p className="whitespace-pre-wrap break-words text-sm">{n.preview}</p>{!n.read && <button className={button} onClick={() => void mark(n.id)}>읽음으로 표시</button>}</li>)}</ul>
    {query.data?.pages[0].items.length === 0 && <p className="text-sm text-slate-500">새 알림이 없습니다.</p>}{query.hasNextPage && <button className={button} onClick={() => void query.fetchNextPage()}>이전 알림</button>}
  </section>;
}

type NodeLink = { source_id: number; target_id: number; node_id: number; content: string; label: string; direction: string };
export function KnowledgeLinks({ node, readOnly, onClose }: { node: Knowledge; readOnly: boolean; onClose: () => void }) {
  const url = `/projects/${node.project_id}/knowledge/${node.id}/links`;
  const query = useInfiniteQuery({ queryKey: ["workspace", node.project_id, "links", node.id], initialPageParam: 0,
    queryFn: async ({ pageParam, signal }) => (await apiClient.get<Page<NodeLink>>(url, { signal, params: { after: pageParam } })).data,
    getNextPageParam: page => page.next_cursor == null ? undefined : Number(page.next_cursor) });
  const [target, setTarget] = useState(""), [label, setLabel] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const mutate = async (link?: NodeLink) => {
    setBusy(true); setError("");
    try { if (link) await apiClient.delete(`/projects/${node.project_id}/knowledge/${link.source_id}/links/${link.target_id}`); else await apiClient.put(url, { target_id: Number(target), label }); await query.refetch(); setTarget(""); setLabel(""); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <ProjectDialog title={`아이디어 #${node.id} 연결`} onClose={onClose} busy={busy}><p className="mb-4 text-sm text-slate-500">같은 프로젝트의 관련 아이디어를 연결하면 양쪽에서 확인할 수 있습니다.</p>
    {query.data?.pages.flatMap(p => p.items).map((r, i) => <article className="space-y-2 border-b py-3" key={`${r.source_id}:${r.target_id}:${i}`}><p className="text-xs text-slate-500">{r.direction === "incoming" ? "이 아이디어를 참조" : "참조하는 아이디어"} · #{r.node_id} · {r.label}</p><p className="whitespace-pre-wrap break-words text-sm">{r.content}</p>{!readOnly && <button className={button} disabled={busy} onClick={() => void mutate(r)}>연결 해제</button>}</article>)}
    {query.hasNextPage && <button className={button} onClick={() => void query.fetchNextPage()}>연결 더 보기</button>}
    {!readOnly && <form className="mt-5 space-y-3" onSubmit={e => { e.preventDefault(); void mutate(); }}><label className="block text-sm">연결할 노드 번호<input className={field} required type="number" min={1} value={target} onChange={e => setTarget(e.target.value)} /></label><label className="block text-sm">연결 설명<input className={field} maxLength={120} value={label} onChange={e => setLabel(e.target.value)} /></label><button className={primary} disabled={busy}>지식 연결</button></form>}
    {(error || query.error) && <p role="alert" className="mt-3">{error || workspaceError(query.error)}</p>}
  </ProjectDialog>;
}

export function TaskDependencies({ projectId, task, readOnly, onSaved }: { projectId: number; task: Task; readOnly: boolean; onSaved: (task: Task) => void }) {
  const url = `/projects/${projectId}/tasks/${task.id}/dependencies`;
  const query = useQuery({ queryKey: ["workspace", projectId, "dependencies", task.id], queryFn: async () => (await apiClient.get<Task[]>(url)).data });
  const [search, setSearch] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const candidates = useQuery({ queryKey: ["workspace", projectId, "dependency-search", search], enabled: !!search,
    queryFn: async ({ signal }) => (await apiClient.get<Page<Task>>(`/projects/${projectId}/tasks`, { signal, params: { q: search, limit: 20 } })).data });
  const save = async (requires: string[]) => {
    setBusy(true); setError("");
    try { const result = await apiClient.put<Task>(url, { requires, expected_version: task.version }); onSaved(result.data); await query.refetch(); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <section className="mt-6 space-y-3 border-t pt-4" aria-label="선행 과제"><h3 className="font-medium">먼저 완료할 과제</h3>{query.data?.map(r => <div key={r.id} className="flex items-center justify-between gap-2 text-sm"><span>{r.status === "DONE" ? "✓" : "○"} {r.title}</span>{!readOnly && <button type="button" disabled={busy} className={button} onClick={() => void save(query.data!.filter(t => t.id !== r.id).map(t => t.id))}>제거</button>}</div>)}
    {!readOnly && <><label className="block text-sm">선행 과제 검색<input className={field} value={search} maxLength={200} onChange={e => setSearch(e.target.value)} /></label>{candidates.data?.items.filter(r => r.id !== task.id && !query.data?.some(t => t.id === r.id)).map(r => <button key={r.id} type="button" disabled={busy || !query.data} className={`${button} mr-2 mb-2`} onClick={() => void save([...(query.data ?? []).map(t => t.id), r.id])}>추가: {r.title}</button>)}</>}
    {(error || query.error) && <p role="alert">{error || workspaceError(query.error)}</p>}
  </section>;
}
