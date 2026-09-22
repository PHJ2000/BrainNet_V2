"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";
import { button, workspaceError } from "./api";

export default function ProjectTrash() {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState<number | null>(null), [error, setError] = useState("");
  const cache = useQueryClient();
  const query = useQuery({ queryKey: ["workspace-trash"], enabled: open, retry: false,
    queryFn: async ({ signal }) => (await apiClient.get<{id: number; name: string}[]>("/workspace/trash", { signal })).data });
  const restore = async (id: number) => {
    if (busy !== null) return;
    setBusy(id); setError("");
    try { await apiClient.post(`/workspace/trash/${id}/restore`); await Promise.all([query.refetch(), cache.invalidateQueries({ queryKey: ["projects"] }), cache.invalidateQueries({ queryKey: ["knowledge"] })]); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(null); }
  };
  return <section className="border-t border-slate-200 pt-5"><button className={button} aria-expanded={open} onClick={() => setOpen(value => !value)}>프로젝트 휴지통</button>
    {open && <div className="mt-4 space-y-3"><p className="text-sm text-slate-500">소유한 프로젝트를 복원합니다. 삭제 전의 미사용 초대 코드는 폐기됩니다.</p>
      {(error || query.error) && <p role="alert">{error || workspaceError(query.error)} <button className="underline" onClick={() => void query.refetch()}>다시 불러오기</button></p>}
      {query.isLoading && <p role="status">휴지통을 불러오는 중…</p>}
      {!query.error && query.data?.map(project => <div key={project.id} className="flex items-center justify-between gap-3 border-b py-3 text-sm"><span>{project.name}</span><button className={button} disabled={busy !== null} onClick={() => void restore(project.id)}>{busy === project.id ? "복원 중…" : "복원"}</button></div>)}
      {!query.isLoading && !query.error && !query.data?.length && <p className="text-sm text-slate-500">삭제한 프로젝트가 없습니다.</p>}
    </div>}
  </section>;
}
