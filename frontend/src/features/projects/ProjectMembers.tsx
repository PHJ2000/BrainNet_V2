"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";
import ProjectDialog from "./ProjectDialog";
import { projectError } from "./projectError";

type Member = { user_id: number; email: string; role: "OWNER" | "EDITOR" | "VIEWER" };
type Invitation = { email: string; role: string; expires_at: string };
export default function ProjectMembers({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [remove, setRemove] = useState<number | null>(null);
  const query = useQuery({ queryKey: ["members", projectId], enabled: open, retry: false,
    queryFn: async ({ signal }) => {
      const members = (await apiClient.get<Member[]>(`/projects/${projectId}/members`, { signal })).data;
      const invitations = canManage ? (await apiClient.get<Invitation[]>(`/projects/${projectId}/invitations`, { signal })).data : [];
      return { members, invitations };
    } });
  const run = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true); setError("");
    try { await action(); setRemove(null); await query.refetch(); }
    catch (e) { setError(projectError(e)); }
    finally { setBusy(false); }
  };
  return <>
    <button onClick={() => setOpen(true)} className="rounded border bg-white px-4 py-2 text-sm">멤버 관리</button>
    {open && <ProjectDialog title="프로젝트 멤버" busy={busy} onClose={() => setOpen(false)}>
      {query.isLoading && <p role="status">멤버를 불러오는 중…</p>}
      {(error || query.error) && <div role="alert"><p>{error || projectError(query.error)}</p><button onClick={() => void query.refetch()} className="my-2 underline">멤버 다시 불러오기</button></div>}
      <ul className="space-y-4">{query.data?.members.map(member => <li key={member.user_id} className="border-b pb-3">
        <p className="mb-2 break-all text-sm">{member.email}</p>
        {canManage && member.role !== "OWNER" ? <div className="flex items-center gap-3">
          <select aria-label={`${member.email} 권한`} value={member.role} disabled={busy} className="rounded border p-2 text-sm"
            onChange={event => void run(() => apiClient.patch(`/projects/${projectId}/members/${member.user_id}`, { role: event.target.value }))}>
            <option value="EDITOR">편집 가능</option><option value="VIEWER">읽기 전용</option>
          </select>
          <button disabled={busy} onClick={() => setRemove(member.user_id)} className="text-sm text-red-700 underline">내보내기</button>
          {remove === member.user_id && <button disabled={busy} className="rounded border border-red-300 p-2 text-sm text-red-700"
            onClick={() => void run(() => apiClient.delete(`/projects/${projectId}/members/${member.user_id}`))}>내보내기 확인</button>}
        </div> : <span className="text-sm text-slate-500">{member.role === "OWNER" ? "소유자" : member.role === "VIEWER" ? "읽기 전용" : "편집 가능"}</span>}
      </li>)}</ul>
      {canManage && <section className="mt-5 space-y-3"><h3 className="font-semibold">대기 중인 초대</h3>
        {!query.data?.invitations.length && <p className="text-sm text-slate-500">대기 중인 초대가 없습니다.</p>}
        {query.data?.invitations.map(invite => <div key={invite.email} className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>{invite.email} · {invite.role === "VIEWER" ? "읽기 전용" : "편집 가능"}</span>
          <button disabled={busy} className="text-red-700 underline" onClick={() => void run(() => apiClient.delete(`/projects/${projectId}/invitations`, { params: { email: invite.email } }))}>초대 철회</button>
        </div>)}
      </section>}
    </ProjectDialog>}
  </>;
}
