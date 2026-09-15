"use client";
import { useState } from "react";
import axios from "axios";
import { apiClient } from "@/lib/apiClient";
import BackupImport, { BACKUP_EXCLUSIONS } from "./BackupImport";
const button = "rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-indigo-600";

async function download(pid: number, root: string, inactive: boolean, format: "markdown" | "json") {
  const response = await apiClient.get(`/projects/${pid}/export/${format}`, {
    params: format === "markdown" ? { root_id: root || undefined, include_inactive: inactive } : {}, responseType: "blob", timeout: 30000 });
  if (!response.data.size) throw new Error("빈 파일을 받았어요.");
  const disposition = String(response.headers["content-disposition"] ?? "");
  const match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const name = match ? decodeURIComponent(match[1]) : `brainnet.${format === "markdown" ? "md" : "json"}`;
  const url = URL.createObjectURL(response.data);
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ProjectFiles({ projectId, nodes }: {
  projectId: number; nodes: { id: string; label: string }[];
}) {
  const [open, setOpen] = useState(false);
  const [root, setRoot] = useState("");
  const [inactive, setInactive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (format: "markdown" | "json") => {
    if (busy) return;
    setBusy(true); setError("");
    try { await download(projectId, root, inactive, format); }
    catch (e) {
      if (axios.isAxiosError(e) && e.response?.data instanceof Blob) {
        try { const body = JSON.parse(await e.response.data.text()); setError(`내보내기 실패: ${body.message}`); }
        catch { setError("파일을 받지 못했어요. 연결과 권한을 확인해 주세요."); }
      } else setError("파일을 받지 못했어요. 연결과 권한을 확인해 주세요.");
    } finally { setBusy(false); }
  };
  return <>
    <button className={`${button} absolute right-28 top-4 z-20`} onClick={() => setOpen(v => !v)}>파일</button>
    {open && <section aria-label="프로젝트 파일" className="absolute right-4 top-16 z-30 w-80 rounded-lg border bg-white p-4 shadow-lg">
      <div className="mb-3 flex justify-between"><h2 className="font-semibold">프로젝트 내보내기</h2><button className={button} onClick={() => setOpen(false)}>닫기</button></div>
      <p className="mb-3 text-sm text-slate-600">검색·태그 필터·접기와 관계없이 원본 범위를 저장해요.</p>
      <label className="block text-sm">Markdown 범위
        <select aria-label="Markdown 범위" className="my-2 w-full rounded border p-2" value={root} onChange={e => setRoot(e.target.value)}>
          <option value="">전체 프로젝트</option>
          {nodes.map(n => <option key={n.id} value={n.id}>{n.label.slice(0, 45)} · {n.id}번 가지</option>)}
        </select>
      </label>
      <label className="mb-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={inactive} onChange={e => setInactive(e.target.checked)} />GHOST·ARCHIVED 포함</label>
      <button className={button} disabled={busy} onClick={() => void save("markdown")}>Markdown 저장</button>
      <div className="my-4 border-t pt-3"><p className="mb-2 text-sm">JSON은 프로젝트 전체와 모든 노드 상태를 저장해요. {BACKUP_EXCLUSIONS}</p>
        <button className={button} disabled={busy} onClick={() => void save("json")}>전체 JSON 백업 저장</button></div>
      <BackupImport />
      {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    </section>}
  </>;
}
