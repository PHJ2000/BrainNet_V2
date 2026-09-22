"use client";
import { useState } from "react";
import Link from "next/link";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";
import { button, field, primary, workspaceError, type Knowledge, type Page, type Task } from "./api";
import { newTask, TaskEditor } from "./TaskBoard";
import { useWorkspaceDraft } from "./useWorkspaceDraft";
import { AssetList, SaveAsset } from "./PersonalAssets";

export default function KnowledgeLibrary({ projectId, readOnly = true, onSelectAI }: { projectId?: number; readOnly?: boolean; onSelectAI?: (node: Knowledge) => void }) {
  const [input, setInput] = useState(""), [search, setSearch] = useState(""), [bookmarked, setBookmarked] = useState(false);
  const [savedScope, setSavedScope] = useState<number | null>(null);
  const scope = projectId ?? savedScope ?? undefined;
  const [error, setError] = useState(""), [busy, setBusy] = useState<number | null>(null), [task, setTask] = useState<Task | null>(null);
  const cache = useQueryClient();
  const storage = useWorkspaceDraft<Task>(projectId ?? 0, "task");
  const query = useInfiniteQuery({ queryKey: ["knowledge", scope, search, bookmarked], initialPageParam: 0, retry: false,
    queryFn: async ({ signal, pageParam }) => (await apiClient.get<Page<Knowledge>>("/workspace/knowledge", { signal, params: { q: search, project_id: scope, bookmarked, after: pageParam } })).data,
    getNextPageParam: page => page.next_cursor == null ? undefined : Number(page.next_cursor) });
  const toggle = async (node: Knowledge) => {
    if (busy !== null) return;
    setBusy(node.id); setError("");
    try { await apiClient.request({ method: node.bookmarked ? "DELETE" : "PUT", url: `/projects/${node.project_id}/bookmarks/${node.id}` }); await cache.invalidateQueries({ queryKey: ["knowledge"] }); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(null); }
  };
  const nodes = query.data?.pages.flatMap(page => page.items) ?? [];
  return <section aria-label="지식 라이브러리" className="space-y-5">
    <header><h2 className="text-xl font-semibold">{projectId ? "프로젝트 지식" : "내 지식 라이브러리"}</h2><p className="mt-1 text-sm text-slate-500">{projectId ? "아이디어를 찾아 과제로 연결하거나 AI 검토에 사용하세요." : "참여 중인 프로젝트의 아이디어를 한곳에서 검색하세요."} 북마크는 나에게만 보입니다.</p></header>
    <form className="flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); setSearch(input.trim()); }}>
      <input aria-label="지식 검색어" className={`${field} !mt-0 min-w-40 flex-1 !w-auto`} maxLength={200} placeholder="아이디어 내용으로 검색" value={input} onChange={e => setInput(e.target.value)} />
      <button className={primary}>검색</button><button type="button" aria-pressed={bookmarked} className={button} onClick={() => setBookmarked(value => !value)}>{bookmarked ? "★ 내 북마크" : "☆ 북마크만 보기"}</button>
    </form>
    <div className="flex flex-wrap items-start justify-between gap-3"><AssetList kind="SEARCH" scopeProjectId={projectId} onSearch={value => { setInput(value.q); setSearch(value.q); setBookmarked(value.bookmarked); setSavedScope(value.project_id); }} /><SaveAsset kind="SEARCH" search={{ q: search, bookmarked, project_id: scope ?? null }} /></div>
    {!projectId && savedScope && <p className="text-xs text-slate-500">저장 검색 범위: 프로젝트 #{savedScope} <button className="ml-2 underline" onClick={() => setSavedScope(null)}>모든 프로젝트로 확대</button></p>}
    {query.isLoading && <p role="status">아이디어를 찾는 중…</p>}
    {(error || query.error) && <div role="alert" className="text-sm text-red-700">{error || workspaceError(query.error)} <button className={button} onClick={() => void query.refetch()}>다시 불러오기</button></div>}
    {!query.error && <ul className="divide-y divide-slate-200 border-y border-slate-200">{nodes.map(node => <li key={node.id} className="py-4">
      <div className="mb-2 flex items-center justify-between gap-3 text-xs text-slate-500"><Link className="hover:text-indigo-700" href={`/dashboard/projects/${node.project_id}`}>{node.project_name} · #{node.id}</Link><button aria-label={node.bookmarked ? `북마크 해제 ${node.id}` : `북마크 저장 ${node.id}`} aria-pressed={node.bookmarked} className="rounded border px-2 py-1 text-sm" disabled={busy !== null} onClick={() => void toggle(node)}>{node.bookmarked ? "★ 저장됨" : "☆ 저장"}</button></div>
      <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{node.content}</p>
      {projectId && !readOnly && <div className="mt-3 flex flex-wrap gap-3"><button disabled={!!storage.draft} className="text-sm font-medium text-indigo-700 hover:underline disabled:opacity-40" onClick={() => setTask(newTask(node.id, node.content))}>실행 과제로 연결</button>{storage.draft && <span className="text-xs text-slate-500">실행 보드에서 기존 초안을 먼저 처리해 주세요.</span>}{onSelectAI && <button className="text-sm font-medium text-indigo-700 hover:underline" onClick={() => onSelectAI(node)}>AI 검토에 추가</button>}</div>}
    </li>)}</ul>}
    {!query.isLoading && !query.error && !nodes.length && <p className="py-8 text-center text-sm text-slate-500">일치하는 아이디어가 없습니다. 검색어나 북마크 필터를 바꿔 보세요.</p>}
    {query.hasNextPage && <button className={button} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>아이디어 더 보기</button>}
    {task && projectId && <TaskEditor task={task} projectId={projectId} onClose={() => setTask(null)} />}
  </section>;
}
