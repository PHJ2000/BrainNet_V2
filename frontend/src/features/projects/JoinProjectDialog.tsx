"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import ProjectDialog from "./ProjectDialog";
import { joinProject } from "./projectApi";
import { projectError } from "./projectError";

export default function JoinProjectDialog({ onClose }: { onClose: () => void }) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  const router = useRouter();
  return <ProjectDialog title="초대 코드로 참여" onClose={onClose} busy={busy}>
    <form className="space-y-4" onSubmit={async event => {
      event.preventDefault(); if (busy || !token.trim()) return;
      setBusy(true); setError("");
      try {
        const joined = await joinProject(token.trim());
        await client.invalidateQueries({ queryKey: ["projects"] });
        router.push(`/dashboard/projects/${joined.project_id}`); onClose();
      } catch (error) { setError(projectError(error)); }
      finally { setBusy(false); }
    }}>
      <p className="text-sm leading-6 text-slate-500">초대받은 이메일 계정으로 로그인한 뒤 전달받은 코드를 입력하세요.</p>
      <label className="block text-sm">초대 코드<input autoFocus required value={token} disabled={busy} onChange={e => setToken(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 focus:ring-2 focus:ring-blue-500" /></label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button disabled={busy || !token.trim()} className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-40">{busy ? "참여 중..." : "프로젝트 참여"}</button>
    </form>
  </ProjectDialog>;
}
