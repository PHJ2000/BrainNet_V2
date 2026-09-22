"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import ProjectDialog from "@/features/projects/ProjectDialog";
import { button, field, primary, useWorkspaceList, workspaceError, type Knowledge, type Proposal } from "./api";

const modes = { EXPAND: "아이디어 확장", SUMMARY: "내용 요약", ACTION: "실행 과제 제안" };
const labels: Record<string, string> = { RUNNING: "생성 중", READY: "검토 대기", FAILED: "생성 실패", INTERRUPTED: "요청 중단", ACCEPTED: "과제로 채택됨" };
const errors: Record<string, string> = { AI_PROVIDER_NOT_CONFIGURED: "AI 제공자 설정이 없습니다.", AI_PROVIDER_TIMEOUT: "제공자 응답 시간이 초과되었습니다.", AI_PROVIDER_UNAVAILABLE: "제공자 요청에 실패했습니다.", AI_REQUEST_INTERRUPTED: "서버 재시작 또는 연결 중단으로 완료되지 않았습니다." };

function AcceptDialog({ proposal, projectId, onClose }: { proposal: Proposal; projectId: number; onClose: () => void }) {
  const [title, setTitle] = useState((proposal.output?.split("\n")[0] || "AI 검토 과제").slice(0, 240));
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const cache = useQueryClient();
  const accept = async () => {
    setBusy(true); setError("");
    try { await apiClient.post(`/projects/${projectId}/proposals/${proposal.id}/accept`, { title }); await cache.invalidateQueries({ queryKey: ["workspace", projectId] }); onClose(); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <ProjectDialog title="검토한 제안을 실행 과제로" busy={busy} onClose={onClose}><form className="space-y-4" onSubmit={e => { e.preventDefault(); if (!busy) void accept(); }}>
    <label className="block text-sm">과제 제목<input aria-label="채택할 과제 제목" required maxLength={240} className={field} value={title} onChange={e => setTitle(e.target.value)} disabled={busy} /></label>
    <p className="text-sm leading-6 text-slate-500">제안 전체가 과제 본문에 저장됩니다. 원본 노드가 변경되었으면 새 제안이 필요합니다.</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}<button disabled={busy || !title.trim()} className={primary}>{busy ? "채택 중…" : "과제 생성 확인"}</button>
  </form></ProjectDialog>;
}

export default function AIReview({ projectId, readOnly, enabled, selected, onRemove, onPick }: { projectId: number; readOnly: boolean; enabled: boolean; selected: Knowledge[]; onRemove: (id: number) => void; onPick: () => void }) {
  const query = useWorkspaceList<Proposal>(projectId, "proposals"), cache = useQueryClient();
  const [mode, setMode] = useState<Proposal["mode"]>("ACTION"), [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [review, setReview] = useState<Proposal | null>(null);
  const [pending, setPending] = useState<{id: string; mode: Proposal["mode"]; instruction: string; node_ids: number[]} | null>(null);
  const request = async () => {
    if (busy) return;
    const payload = pending ?? { id: uuid(), mode, instruction, node_ids: selected.map(node => node.id) };
    setPending(payload); setBusy(true); setError("");
    try {
      await apiClient.post(`/projects/${projectId}/proposals`, payload, { timeout: 55000 });
      setPending(null); await cache.invalidateQueries({ queryKey: ["workspace", projectId] });
    } catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <section className="space-y-6" aria-label="AI 검토">
    <header><h2 className="text-xl font-semibold">AI 제안 검토실</h2><p className="mt-1 text-sm text-slate-500">원문을 선택해 제안을 받고, 검토한 내용만 실행 과제로 채택하세요.</p></header>
    {!enabled && <p role="status" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">AI 제공자가 설정되지 않았습니다. 기존 검토 기록은 확인할 수 있습니다.</p>}
    {!readOnly && <form className="space-y-4 border-b border-slate-200 pb-6" onSubmit={e => { e.preventDefault(); void request(); }}>
      <fieldset disabled={busy || !!pending || !enabled} className="space-y-4 disabled:opacity-60">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">검토할 아이디어 · {selected.length}/8</h3><button type="button" className={button} onClick={onPick}>지식에서 선택</button></div>
        {selected.length ? <ul className="space-y-2">{selected.map(node => <li className="flex items-center gap-3 rounded-md bg-slate-50 px-3 py-2 text-sm" key={node.id}><span className="min-w-0 flex-1 truncate">#{node.id} {node.content}</span><button type="button" className="text-slate-500 underline" onClick={() => onRemove(node.id)} aria-label={`선택 해제 ${node.id}`}>해제</button></li>)}</ul> : <p className="text-sm text-slate-500">지식 화면에서 ‘AI 검토에 추가’를 선택하세요.</p>}
        <div className="grid gap-4 md:grid-cols-[180px_1fr]"><label className="text-sm">요청 종류<select className={field} value={mode} onChange={e => setMode(e.target.value as Proposal["mode"])}>{Object.entries(modes).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label className="text-sm">검토 요청 · 선택<textarea aria-label="AI 검토 요청" className={field} rows={2} maxLength={1000} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="예: 이번 주에 실행할 수 있는 과제로 정리해 주세요." /></label></div>
      </fieldset>
      <p className="text-xs text-slate-500">선택한 노드의 현재 내용이 AI 제공자에게 전송됩니다. 동시에 1건, 프로젝트당 24시간 내 20건까지 요청할 수 있습니다.</p>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button className={primary} disabled={busy || !enabled || (!pending && !selected.length)}>{busy ? "제안을 생성하는 중…" : pending ? "같은 요청 결과 확인" : "AI 제안 요청"}</button>
      {pending && !busy && <button type="button" className={`${button} ml-2`} onClick={() => { void query.refetch(); setPending(null); setError(""); }}>요청 목록 확인 후 새 요청 준비</button>}
    </form>}
    <div className="flex items-center justify-between"><h3 className="font-semibold">검토 기록</h3><button className={button} onClick={() => void query.refetch()}>기록 새로고침</button></div>
    {query.isLoading && <p role="status">기록을 불러오는 중…</p>}
    {query.error ? <p role="alert">{workspaceError(query.error)}</p> : <ul className="divide-y border-y border-slate-200">{query.data?.pages.flatMap(page => page.items).map(row => <li className="py-5" key={row.id}>
      <div className="mb-3 flex flex-wrap justify-between gap-2"><span className="text-sm font-semibold">{modes[row.mode]} <span className="ml-2 font-normal text-indigo-700">{labels[row.status] ?? row.status}</span></span><time className="text-xs text-slate-500">{new Date(row.created_at).toLocaleString("ko-KR")}</time></div>
      {row.instruction && <p className="mb-2 text-sm text-slate-500">요청: {row.instruction}</p>}
      {row.output && <p className="whitespace-pre-wrap break-words text-sm leading-7">{row.output}</p>}
      {row.error_code && <p className="text-sm text-red-700">{errors[row.error_code] ?? "요청에 실패했습니다."} 필요하면 새 요청을 시작해 주세요.</p>}
      <details className="mt-3 text-sm"><summary className="cursor-pointer text-slate-500">요청 당시 원문 {row.sources.length}개</summary><ul className="mt-2 space-y-3 border-l-2 border-slate-200 pl-3">{row.sources.map(source => <li key={source.id} className="whitespace-pre-wrap break-words text-slate-600">#{source.id} · 버전 {source.version}<br />{source.content}</li>)}</ul></details>
      {!readOnly && row.status === "READY" && <button className={`${button} mt-4`} onClick={() => setReview(row)}>검토 후 과제로 채택</button>}
    </li>)}</ul>}
    {!query.isLoading && !query.error && !query.data?.pages[0].items.length && <p className="text-sm text-slate-500">아직 요청한 제안이 없습니다.</p>}
    {query.hasNextPage && <button className={button} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>이전 기록 더 보기</button>}
    {review && <AcceptDialog proposal={review} projectId={projectId} onClose={() => setReview(null)} />}
  </section>;
}
