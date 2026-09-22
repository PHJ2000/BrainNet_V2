"use client";
import { useState } from "react";
import { apiClient } from "@/lib/apiClient";
import { button, workspaceError } from "./api";
import { SaveAsset } from "./PersonalAssets";

export default function WorkspaceExport({ projectId }: { projectId: number }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const download = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const { data } = await apiClient.get(`/projects/${projectId}/export/workspace`, { responseType: "blob" });
      const url = URL.createObjectURL(data), link = document.createElement("a");
      link.href = url; link.download = `brainnet-workspace-${projectId}.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <details className="shrink-0 border-t border-slate-200 px-4 py-2 text-xs text-slate-500"><summary className="cursor-pointer">작업 공간 백업</summary><div className="flex flex-wrap items-center gap-3 py-3"><p className="max-w-2xl leading-5">그래프·과제·토론·AI 기록·내 북마크를 저장합니다. 계정·권한·담당자·투표·변경 이력은 제외됩니다. 대시보드에서 새 프로젝트로 복원할 수 있습니다.</p><button className={button} disabled={busy} onClick={() => void download()}>{busy ? "내보내는 중…" : "작업 공간 JSON 다운로드"}</button><SaveAsset kind="TEMPLATE" projectId={projectId} />{error && <p role="alert">{error}</p>}</div></details>;
}
