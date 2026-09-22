"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/apiClient";
import type { Project, User } from "@/types/api";
import ProjectMembers from "./ProjectMembers";
import ProjectDialog from "./ProjectDialog";
import { deleteProject, inviteProject, updateProject } from "./projectApi";
import { projectError } from "./projectError";

const field = "mt-1 w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500";
const button = "rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40";

export default function ProjectSettings({ project }: { project: Project }) {
  const [open, setOpen] = useState(false);
  const { data: user } = useQuery({ queryKey: ["me"], queryFn: async ({ signal }) =>
    (await apiClient.get<User>("/users/me", { signal })).data, retry: false });
  if (!user) return null;
  if (String(user.id) !== String(project.owner_id)) return <ProjectMembers projectId={project.id} canManage={false} />;
  return <>
    <ProjectMembers projectId={project.id} canManage />
    <button onClick={() => setOpen(true)} className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm hover:bg-slate-50">프로젝트 설정</button>
    {open && <SettingsForm project={project} onClose={() => setOpen(false)} />}
  </>;
}

function SettingsForm({ project, onClose }: { project: Project; onClose: () => void }) {
  const client = useQueryClient();
  const router = useRouter();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [role, setRole] = useState<"EDITOR" | "VIEWER">("EDITOR");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (error) { setError(projectError(error)); }
    finally { setBusy(false); }
  };
  return <ProjectDialog title="프로젝트 설정" onClose={onClose} busy={busy}>
    <fieldset disabled={busy} className="space-y-6 disabled:opacity-70">
      <form className="space-y-3" onSubmit={event => {
        event.preventDefault(); if (!name.trim()) return;
        void run(async () => {
          const saved = await updateProject(project.id, { name: name.trim(), description });
          await client.cancelQueries({ queryKey: ["project", Number(project.id)] });
          client.setQueryData(["project", Number(project.id)], saved);
          await client.invalidateQueries({ queryKey: ["projects"] });
          setMessage("프로젝트 정보를 저장했습니다.");
        });
      }}>
        <label className="block text-sm">프로젝트 이름<input className={field} value={name} onChange={e => setName(e.target.value)} maxLength={120} required /></label>
        <label className="block text-sm">설명<textarea className={field} rows={3} value={description} onChange={e => setDescription(e.target.value)} /></label>
        <button className={button} disabled={busy || !name.trim()}>변경 저장</button>
      </form>
      <form className="space-y-3 border-t border-slate-200 pt-5" onSubmit={event => {
        event.preventDefault(); setToken("");
        void run(async () => { setToken((await inviteProject(project.id, email.trim(), role)).invite_token); });
      }}>
        <h3 className="font-medium">멤버 초대</h3>
        <p className="text-sm leading-6 text-slate-500">코드는 7일 동안 유효하며 입력한 이메일 계정만 사용할 수 있습니다. 이메일은 자동 발송되지 않습니다. 재발급하면 이전 코드는 무효가 됩니다.</p>
        <label className="block text-sm">초대할 이메일<input type="email" required maxLength={120} className={field} value={email} onChange={e => { setEmail(e.target.value); setToken(""); }} /></label>
        <label className="block text-sm">초대 권한<select className={field} value={role} onChange={e => { setRole(e.target.value as "EDITOR" | "VIEWER"); setToken(""); }}><option value="EDITOR">편집 가능</option><option value="VIEWER">읽기 전용</option></select></label>
        <button className={button} disabled={busy}>초대 코드 발급</button>
        {token && <div className="space-y-2">
          <label className="block text-sm">초대 코드<input readOnly value={token} className={`${field} font-mono text-xs`} onFocus={e => e.target.select()} /></label>
          <button type="button" className="text-sm text-blue-700 underline" onClick={() => void run(async () => {
            try { await navigator.clipboard.writeText(token); setMessage("초대 코드를 복사했습니다."); }
            catch { setError("자동 복사를 사용할 수 없습니다. 코드 입력란을 선택해 직접 복사해 주세요."); }
          })}>코드 복사</button>
        </div>}
      </form>
      <form className="space-y-3 border-t border-slate-200 pt-5" onSubmit={event => {
        event.preventDefault(); if (confirmation !== project.name) return;
        void run(async () => {
          await deleteProject(project.id);
          await client.cancelQueries({ queryKey: ["project", Number(project.id)] });
          client.removeQueries({ queryKey: ["project", Number(project.id)] });
          void client.invalidateQueries({ queryKey: ["projects"] });
          router.replace("/dashboard"); onClose();
        });
      }}>
        <h3 className="font-medium text-red-700">프로젝트 삭제</h3>
        <p className="text-sm text-slate-500">삭제하면 모든 멤버가 접근할 수 없습니다. 확인을 위해 “{project.name}”을 입력하세요.</p>
        <label className="block text-sm">삭제 확인 이름<input className={field} value={confirmation} onChange={e => setConfirmation(e.target.value)} autoComplete="off" /></label>
        <button disabled={busy || confirmation !== project.name} className="rounded-md border border-red-300 px-4 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-40">프로젝트 삭제</button>
      </form>
    </fieldset>
    {busy && <p role="status" className="mt-4 text-sm text-slate-500">처리 중...</p>}
    {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
    {message && <p role="status" className="mt-4 text-sm text-blue-700">{message}</p>}
  </ProjectDialog>;
}
