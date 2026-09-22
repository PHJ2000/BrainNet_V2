"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";
import { button, field, workspaceError } from "./api";

type Policy = { daily_limit: number; input_limit: number; version: number; used: number };
function Editor({ value, projectId }: { value: Policy; projectId: number }) {
  const [daily, setDaily] = useState(value.daily_limit), [input, setInput] = useState(value.input_limit), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const cache = useQueryClient();
  const save = async () => {
    setBusy(true); setError("");
    try { await apiClient.put(`/projects/${projectId}/proposals/policy`, { daily_limit: daily, input_limit: input, expected_version: value.version }); await cache.invalidateQueries({ queryKey: ["workspace", projectId, "ai-policy"] }); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <form onSubmit={e => { e.preventDefault(); void save(); }} className="mt-4 flex flex-wrap items-end gap-3"><label className="text-sm">24시간 요청 한도<input className={field} type="number" min={0} max={100} required value={daily} onChange={e => setDaily(Number(e.target.value))} /></label><label className="text-sm">요청당 원문 글자 수<input className={field} type="number" min={100} max={16000} required value={input} onChange={e => setInput(Number(e.target.value))} /></label><button className={button} disabled={busy}>사용량 제한 저장</button>{error && <p className="w-full" role="alert">{error}</p>}</form>;
}
export default function AIBudget({ projectId, owner }: { projectId: number; owner: boolean }) {
  const query = useQuery({ queryKey: ["workspace", projectId, "ai-policy"], queryFn: async ({ signal }) => (await apiClient.get<Policy>(`/projects/${projectId}/proposals/policy`, { signal })).data });
  return <details className="border-b border-slate-200 pb-4"><summary className="cursor-pointer text-sm text-slate-600">AI 사용량 · 최근 24시간 {query.data ? `${query.data.used} / ${query.data.daily_limit}건` : "확인 중"}</summary><p className="mt-3 text-xs leading-6 text-slate-500">요청 건수와 원문 크기로 소비량을 제한합니다. 금액이나 실제 토큰 요금의 상한은 아닙니다. 한도를 0으로 설정하면 새 요청을 중지합니다. 취소·실패한 요청도 사용량에 포함됩니다.</p>{query.error && <p role="alert">{workspaceError(query.error)}</p>}{owner && query.data && <Editor key={query.data.version} value={query.data} projectId={projectId} />}</details>;
}
