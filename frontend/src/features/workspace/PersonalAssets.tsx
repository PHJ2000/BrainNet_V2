"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import { button, field, primary, workspaceError } from "./api";
import ProjectDialog from "@/features/projects/ProjectDialog";

export type SearchPreset = { q: string; bookmarked: boolean; project_id: number | null };
type Asset = { id: string; name: string; kind: "SEARCH" | "TEMPLATE"; search: SearchPreset | null };

export function SaveAsset({ kind, projectId, search }: { kind: "SEARCH" | "TEMPLATE"; projectId?: number; search?: SearchPreset }) {
  const [open, setOpen] = useState(false), [name, setName] = useState(""), [id, setId] = useState(() => uuid());
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const cache = useQueryClient();
  const save = async () => {
    setBusy(true); setError("");
    try { await apiClient.post("/workspace/assets", { id, name, kind, ...(search ?? { project_id: projectId }) }); await cache.invalidateQueries({ queryKey: ["personal-assets", kind] }); setOpen(false); setName(""); setId(uuid()); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(false); }
  };
  return <><button className={button} onClick={() => setOpen(true)}>{kind === "SEARCH" ? "현재 검색 저장" : "내 템플릿으로 저장"}</button>
    {open && <ProjectDialog title={kind === "SEARCH" ? "검색 조건 저장" : "프로젝트 템플릿 저장"} busy={busy} onClose={() => setOpen(false)}><form className="space-y-4" onSubmit={e => { e.preventDefault(); if (!busy) void save(); }}>
      <label className="block text-sm">저장 이름<input aria-label="저장 이름" className={field} required maxLength={80} value={name} onChange={e => { setName(e.target.value); setId(uuid()); }} disabled={busy} /></label>
      <p className="text-sm leading-6 text-slate-500">{kind === "SEARCH" ? "검색어·프로젝트 범위·북마크 필터를 나만 사용할 수 있게 저장합니다." : "현재 그래프·과제·토론·AI 기록·내 북마크의 사본을 개인 템플릿으로 저장합니다. 최대 1 MiB. 이후 원본의 변경은 반영되지 않습니다. 새 프로젝트에는 계정·권한·담당자가 복사되지 않습니다."}</p>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}<button className={primary} disabled={busy || !name.trim()}>{busy ? "저장 중…" : "이름으로 저장"}</button>
    </form></ProjectDialog>}
  </>;
}

export function AssetList({ kind, onSearch, scopeProjectId }: { kind: "SEARCH" | "TEMPLATE"; onSearch?: (value: SearchPreset) => void; scopeProjectId?: number }) {
  const query = useQuery({ queryKey: ["personal-assets", kind], retry: false,
    queryFn: async ({ signal }) => (await apiClient.get<Asset[]>("/workspace/assets", { signal, params: { kind } })).data });
  const [busy, setBusy] = useState<string | null>(null), [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const router = useRouter(), cache = useQueryClient();
  const visible = query.data?.filter(asset => !scopeProjectId || asset.search?.project_id === scopeProjectId) ?? [];
  const create = async (asset: Asset) => {
    if (busy) return;
    setBusy(asset.id); setError("");
    try {
      const me = (await apiClient.get<{id: number}>("/users/me")).data;
      const storageKey = `brainnet:template-import:${me.id}:${asset.id}`;
      const key = localStorage.getItem(storageKey) ?? uuid();
      localStorage.setItem(storageKey, key);
      const result = await apiClient.post<{project_id: number}>(`/workspace/assets/${asset.id}/instantiate`, {}, { headers: { "Idempotency-Key": key } });
      localStorage.removeItem(storageKey);
      await cache.invalidateQueries({ queryKey: ["projects"] }); router.push(`/dashboard/projects/${result.data.project_id}`);
    } catch (e) { setError(workspaceError(e)); } finally { setBusy(null); }
  };
  const remove = async (id: string) => {
    if (busy) return; setBusy(id); setError("");
    try { await apiClient.delete(`/workspace/assets/${id}`); await query.refetch(); setConfirmDelete(null); }
    catch (e) { setError(workspaceError(e)); } finally { setBusy(null); }
  };
  return <section className="space-y-3" aria-label={kind === "SEARCH" ? "저장 검색" : "내 프로젝트 템플릿"}>
    <h3 className="text-sm font-semibold">{kind === "SEARCH" ? "저장 검색" : "내 프로젝트 템플릿"}</h3>
    {(error || query.error) && <p role="alert" className="text-sm text-red-700">{error || workspaceError(query.error)} <button className="underline" onClick={() => void query.refetch()}>다시 불러오기</button></p>}
    {!query.error && <ul className="flex flex-wrap gap-2">{visible.map(asset => <li key={asset.id} className="flex items-center gap-2 rounded border border-slate-200 bg-white p-2 text-sm"><button disabled={!!busy} className="text-indigo-700 hover:underline" onClick={() => kind === "SEARCH" && asset.search ? onSearch?.(asset.search) : void create(asset)}>{asset.name}{kind === "TEMPLATE" ? " → 새 프로젝트" : ""}</button><button aria-label={`${asset.name} 삭제`} className="px-1 text-slate-400" disabled={!!busy} onClick={() => setConfirmDelete(asset.id)}>×</button>{confirmDelete === asset.id && <><button className="text-red-700 underline" disabled={!!busy} onClick={() => void remove(asset.id)}>삭제 확인</button><button onClick={() => setConfirmDelete(null)}>취소</button></>}</li>)}</ul>}
    {!query.isLoading && !query.error && !visible.length && <p className="text-xs text-slate-500">{kind === "SEARCH" ? "자주 쓰는 검색 조건을 저장해 보세요." : "프로젝트의 작업 공간 백업 메뉴에서 템플릿을 저장할 수 있습니다."}</p>}
  </section>;
}
