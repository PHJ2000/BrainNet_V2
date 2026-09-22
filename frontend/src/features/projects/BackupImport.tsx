"use client";
import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import { createRequest } from "@/features/nodes/createRequest";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
export const MAX_BACKUP_BYTES = 10 * 1024 * 1024;
export const BACKUP_EXCLUSIONS = "그래프 전용 백업입니다. 과제·토론·AI 기록·북마크·투표·메트릭·변경 이력·계정·권한·인증 정보는 포함하지 않아요.";
const button = "rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-indigo-600";
interface Preview { name: string; node_count: number; tag_count: number; link_count: number;
  schema_version?: number; task_count?: number; discussion_count?: number; proposal_count?: number; bookmark_count?: number;
  depth_adjustments: { node_ref: string; stored_depth: number; depth: number }[]; states: Record<string, number> }
const message = (e: unknown) => axios.isAxiosError(e) && e.response?.data?.message ?
  `파일 처리 실패: ${e.response.data.message}` : e instanceof Error ? e.message : "연결과 파일을 확인해 주세요.";

export default function BackupImport() {
  const router = useRouter();
  const cache = useQueryClient();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ raw: string; key: string; storageKey: string } | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const inspect = async (file?: File) => {
    pending.current = null; setPreview(null); setError("");
    if (!file) return;
    if (file.size > MAX_BACKUP_BYTES) { setError("10 MiB 이하의 JSON 파일을 선택해 주세요."); return; }
    setBusy(true);
    try {
      const buffer = await file.arrayBuffer();
      const raw = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
      const [response, user, digest] = await Promise.all([
        apiClient.post<Preview>("/projects/import/preview", raw, { timeout: 30000 }),
        apiClient.get<{ id: number }>("/users/me"), crypto.subtle.digest("SHA-256", buffer),
      ]);
      if (!alive.current) return;
      const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
      const storageKey = `brainnet:import:${user.data.id}:${hash}`;
      const key = localStorage.getItem(storageKey) || uuid();
      // Save before any write. Reselecting the file after reload resumes this same key.
      localStorage.setItem(storageKey, key);
      pending.current = { raw, key, storageKey }; setPreview(response.data);
    } catch (e) { if (alive.current) setError(message(e)); }
    finally { if (alive.current) setBusy(false); }
  };
  const restore = async () => {
    if (busy || !pending.current) return;
    const item = pending.current; setBusy(true); setError("");
    try {
      const result = await createRequest(key => apiClient.post<{ project_id: number }>("/projects/import", item.raw,
        { headers: { "Idempotency-Key": key }, timeout: 60000 }), item.key);
      if (!alive.current) return;
      // Refresh the sidebar cache before opening the committed project.
      localStorage.removeItem(item.storageKey);
      await cache.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/dashboard/projects/${result.data.project_id}`);
    } catch (e) { if (alive.current) setError(`${message(e)} 같은 파일로 다시 시도하면 기존 요청을 이어가요.`); }
    finally { if (alive.current) setBusy(false); }
  };
  return <>
    <button className={button} onClick={() => setOpen(true)}>JSON 백업 가져오기</button>
    {open && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <section role="dialog" aria-modal="true" aria-label="JSON 백업 복원" className="max-h-[85vh] w-full max-w-lg overflow-auto rounded-lg bg-white p-6 text-slate-900 shadow-xl">
        <h2 className="mb-3 text-lg font-semibold">새 프로젝트로 복원</h2>
        <p className="mb-2 text-sm">기존 프로젝트를 덮어쓰지 않아요. 최대 10 MiB · 노드 5,000개 · 깊이 100.</p>
        <p className="mb-4 text-sm text-slate-600">v1은 그래프, v2는 과제·토론·AI 기록·내 북마크도 복원합니다. 계정·권한·담당자·투표·변경 이력은 복원하지 않습니다. 작성자는 복원한 계정으로 바뀝니다.</p>
        <label className="block text-sm">백업 JSON 파일<input aria-label="백업 JSON 파일" type="file" accept=".json,application/json" disabled={busy}
          className="my-2 block w-full rounded border p-2" onChange={e => void inspect(e.target.files?.[0])} /></label>
        {preview && <div className="my-4 rounded border bg-slate-50 p-3 text-sm">
          <p className="font-semibold">{preview.name}</p>
          <p>노드 {preview.node_count}개 · 태그 {preview.tag_count}개 · 연결 {preview.link_count}개</p>
          {preview.schema_version === 2 && <p>과제 {preview.task_count}개 · 토론 {preview.discussion_count}개 · AI 기록 {preview.proposal_count}개 · 내 북마크 {preview.bookmark_count}개</p>}
          <p>ACTIVE {preview.states.ACTIVE} · GHOST {preview.states.GHOST} · ARCHIVED {preview.states.ARCHIVED}</p>
          {!!preview.depth_adjustments.length && <details className="mt-2"><summary>기존 깊이 값 {preview.depth_adjustments.length}개를 부모 관계에 맞춰 복원해요.</summary>
            <ul className="max-h-32 overflow-auto">{preview.depth_adjustments.map(a => <li key={a.node_ref}>{a.node_ref}: {a.stored_depth} → {a.depth}</li>)}</ul>
          </details>}
        </div>}
        {error && <p role="alert" className="my-3 whitespace-pre-wrap text-sm text-red-700">{error}</p>}
        <div className="mt-4 flex justify-end gap-2"><button className={button} disabled={busy} onClick={() => setOpen(false)}>닫기</button>
          <button className={button} disabled={busy || !preview} onClick={() => void restore()}>{busy ? "처리 중…" : "새 프로젝트 생성 확인"}</button></div>
      </section>
    </div>}
  </>;
}
