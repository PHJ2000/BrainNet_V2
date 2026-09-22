"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import ProjectDialog from "@/features/projects/ProjectDialog";
import { button, field, primary, useWorkspaceList, workspaceError, type Knowledge, type Proposal } from "./api";
import AIBudget from "./AIBudget";

const modes = { EXPAND: "아이디어 확장", SUMMARY: "내용 요약", ACTION: "실행 과제 제안" };
const labels: Record<string, string> = { QUEUED: "대기 중", CANCELED: "취소됨", RUNNING: "생성 중", READY: "검토 대기", FAILED: "생성 실패", INTERRUPTED: "요청 중단", ACCEPTED: "과제로 채택됨" };
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

export default function AIReview({ projectId, readOnly, owner, enabled, selected, onRemove, onPick }: { projectId: number; readOnly: boolean; owner: boolean; enabled: boolean; selected: Knowledge[]; onRemove: (id: number) => void; onPick: () => void }) {
  const query = useWorkspaceList<Proposal & { actor_id: number }>(projectId, "proposals"), cache = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: async () => (await apiClient.get<{ id: number }>("/users/me")).data });
  const [compared, setCompared] = useState<string[]>([]);
  const comparison = query.data?.pages.flatMap(p => p.items).filter(r => compared.includes(r.id)) ?? [];
  const [mode, setMode] = useState<Proposal["mode"]>("ACTION"), [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [review, setReview] = useState<Proposal | null>(null);
  const [pending, setPending] = useState<{id: string; mode: Proposal["mode"]; instruction: string; node_ids: number[]} | null>(null);
  const request = async () => {
    if (busy) return;
    const payload = pending ?? { id: uuid(), mode, instruction, node_ids: selected.map(node => node.id) };
    setPending(payload); setBusy(true); setError("");
    try {
      await apiClient.post(`/projects/${projectId}/proposals`, payload, { params: { enqueue: true } });
      setPending(null); await cache.invalidateQueries({ queryKey: ["workspace", projectId] });
    } catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  const cancel = async (id: string) => {
    setBusy(true); setError("");
    try { await apiClient.post(`/projects/${projectId}/proposals/${id}/cancel`); await cache.invalidateQueries({ queryKey: ["workspace", projectId] }); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <section className="space-y-6" aria-label="AI 검토">
    <header><h2 className="text-xl font-semibold">AI 제안 검토실</h2><p className="mt-1 text-sm text-slate-500">원문을 선택해 제안을 받고, 검토한 내용만 실행 과제로 채택하세요.</p></header>
    <AIBudget projectId={projectId} owner={owner} />
    {!enabled && <p role="status" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">AI 제공자가 설정되지 않았습니다. 기존 검토 기록은 확인할 수 있습니다.</p>}
    {!readOnly && <form className="space-y-4 border-b border-slate-200 pb-6" onSubmit={e => { e.preventDefault(); void request(); }}>
      <fieldset disabled={busy || !!pending || !enabled} className="space-y-4 disabled:opacity-60">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">검토할 아이디어 · {selected.length}/8</h3><button type="button" className={button} onClick={onPick}>지식에서 선택</button></div>
        {selected.length ? <ul className="space-y-2">{selected.map(node => <li className="flex items-center gap-3 rounded-md bg-slate-50 px-3 py-2 text-sm" key={node.id}><span className="min-w-0 flex-1 truncate">#{node.id} {node.content}</span><button type="button" className="text-slate-500 underline" onClick={() => onRemove(node.id)} aria-label={`선택 해제 ${node.id}`}>해제</button></li>)}</ul> : <p className="text-sm text-slate-500">지식 화면에서 ‘AI 검토에 추가’를 선택하세요.</p>}
        <div className="grid gap-4 md:grid-cols-[180px_1fr]"><label className="text-sm">요청 종류<select className={field} value={mode} onChange={e => setMode(e.target.value as Proposal["mode"])}>{Object.entries(modes).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label className="text-sm">검토 요청 · 선택<textarea aria-label="AI 검토 요청" className={field} rows={2} maxLength={1000} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="예: 이번 주에 실행할 수 있는 과제로 정리해 주세요." /></label></div>
      </fieldset>
      <p className="text-xs text-slate-500">선택한 원문을 AI 제공자에게 전송합니다. 대기열은 프로젝트당 최대 5건이며 한 번에 1건씩 처리합니다. 화면을 닫아도 대기 요청은 유지됩니다. 실행 중 취소는 결과 반영을 막지만 이미 발생한 제공자 비용을 취소하지는 못합니다.</p>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button className={primary} disabled={busy || !enabled || (!pending && !selected.length)}>{busy ? "제안을 생성하는 중…" : pending ? "같은 요청 결과 확인" : "AI 제안 요청"}</button>
      {pending && !busy && <button type="button" className={`${button} ml-2`} onClick={() => { void query.refetch(); setPending(null); setError(""); }}>요청 목록 확인 후 새 요청 준비</button>}
    </form>}
    <div className="flex items-center justify-between"><h3 className="font-semibold">검토 기록</h3><button className={button} onClick={() => void query.refetch()}>기록 새로고침</button></div>
    {comparison.length > 0 && <section aria-label="AI 제안 비교" className="space-y-3 border-y py-4"><div className="flex justify-between"><h3 className="font-semibold">선택한 제안 비교 · {comparison.length}/2</h3><button className={button} onClick={() => setCompared([])}>비교 선택 해제</button></div><p className="text-xs text-slate-500">요청과 원문 버전을 함께 확인하세요. 서로 다른 시점의 원문으로 생성된 결과일 수 있습니다.</p><div className="grid gap-5 md:grid-cols-2">{comparison.map(r => <article key={r.id} className="min-w-0"><h4 className="text-sm font-semibold">{modes[r.mode]} · {new Date(r.created_at).toLocaleString("ko-KR")}</h4><p className="my-2 text-xs text-slate-500">{r.instruction || "추가 요청 없음"} · {r.sources.map(s => `#${s.id} v${s.version}`).join(", ")}</p><p className="whitespace-pre-wrap break-words text-sm leading-7">{r.output}</p></article>)}</div></section>}
    {query.isLoading && <p role="status">기록을 불러오는 중…</p>}
    {query.error ? <p role="alert">{workspaceError(query.error)}</p> : <ul className="divide-y border-y border-slate-200">{query.data?.pages.flatMap(page => page.items).map(row => <li className="py-5" key={row.id}>
      <div className="mb-3 flex flex-wrap justify-between gap-2"><span className="text-sm font-semibold">{modes[row.mode]} <span className="ml-2 font-normal text-indigo-700">{labels[row.status] ?? row.status}</span></span><time className="text-xs text-slate-500">{new Date(row.created_at).toLocaleString("ko-KR")}</time></div>
      {row.instruction && <p className="mb-2 text-sm text-slate-500">요청: {row.instruction}</p>}
      {row.output && <p className="whitespace-pre-wrap break-words text-sm leading-7">{row.output}</p>}
      {row.error_code && <p className="text-sm text-red-700">{errors[row.error_code] ?? "요청에 실패했습니다."} 필요하면 새 요청을 시작해 주세요.</p>}
      <details className="mt-3 text-sm"><summary className="cursor-pointer text-slate-500">요청 당시 원문 {row.sources.length}개</summary><ul className="mt-2 space-y-3 border-l-2 border-slate-200 pl-3">{row.sources.map(source => <li key={source.id} className="whitespace-pre-wrap break-words text-slate-600">#{source.id} · 버전 {source.version}<br />{source.content}</li>)}</ul></details>
      {!readOnly && row.status === "READY" && <button className={`${button} mt-4`} onClick={() => setReview(row)}>검토 후 과제로 채택</button>}
      {row.output && <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" aria-label={`비교 선택 ${row.id}`} checked={compared.includes(row.id)} disabled={!compared.includes(row.id) && compared.length >= 2} onChange={e => setCompared(ids => e.target.checked ? [...ids, row.id] : ids.filter(id => id !== row.id))} />결과 비교에 포함</label>}
      {!readOnly && (owner || me.data?.id === row.actor_id) && ["QUEUED", "RUNNING"].includes(row.status) && <button className={`${button} mt-3`} disabled={busy} onClick={() => void cancel(row.id)}>AI 요청 취소</button>}
    </li>)}</ul>}
    {!query.isLoading && !query.error && !query.data?.pages[0].items.length && <p className="text-sm text-slate-500">아직 요청한 제안이 없습니다.</p>}
    {query.hasNextPage && <button className={button} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>이전 기록 더 보기</button>}
    {review && <AcceptDialog proposal={review} projectId={projectId} onClose={() => setReview(null)} />}
  </section>;
}
