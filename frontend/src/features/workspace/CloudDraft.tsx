"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";
import { button, TaskPayload, workspaceError, type Task, type Discussion } from "./api";
import { useWorkspaceDraft } from "./useWorkspaceDraft";

type Cloud = { version: number; updated_at: string; payload: { item: Task | Discussion; attempted: boolean; base_version: number; resolved: boolean } | null };
export default function CloudDraft({ projectId, kind }: { projectId: number; kind: "task" | "discussion" }) {
  const storage = useWorkspaceDraft<Task | Discussion>(projectId, kind), url = `/projects/${projectId}/drafts/${kind}`;
  const query = useQuery({ queryKey: ["workspace", projectId, "cloud-draft", kind], retry: false, queryFn: async ({ signal }) => (await apiClient.get<Cloud | null>(url, { signal })).data });
  const me = useQuery({ queryKey: ["me"], queryFn: async () => (await apiClient.get<{ id: number }>("/users/me")).data });
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const upload = async () => {
    if (!storage.draft) return;
    setBusy(true); setMessage("");
    const { item, attempted } = storage.draft;
    const payload = "title" in item ? { id: item.id, ...TaskPayload(item) } : { id: item.id, body: item.body, node_id: item.node_id };
    try { await apiClient.put(url, { item: payload, attempted, base_version: item.version, resolved: "resolved" in item ? item.resolved : false, expected_version: query.data?.version ?? -1 }); await query.refetch(); setMessage("서버에 보관했습니다. 다른 기기에서 불러올 수 있습니다."); }
    catch (e) { setMessage(workspaceError(e)); } finally { setBusy(false); }
  };
  const download = () => {
    if (!query.data?.payload || storage.draft) return;
    const cloud = query.data.payload;
    const item = { ...cloud.item, version: cloud.base_version, created_at: query.data.updated_at, ...(kind === "discussion" ? { resolved: cloud.resolved, author_id: me.data?.id ?? null } : {}) };
    setMessage(storage.save({ item, attempted: cloud.attempted }) ? "이 탭으로 불러왔습니다. 초안 이어쓰기를 선택하세요." : "브라우저 저장 공간을 사용할 수 없습니다.");
  };
  const remove = async () => {
    if (!query.data) return;
    setBusy(true);
    try { await apiClient.delete(url, { params: { expected_version: query.data.version } }); await query.refetch(); setMessage("서버 사본을 삭제했습니다."); }
    catch (e) { setMessage(workspaceError(e)); } finally { setBusy(false); }
  };
  return <details className="border-b border-slate-200 pb-3 text-sm"><summary className="cursor-pointer text-slate-600">다른 기기와 초안 공유 · 나에게만 공개</summary><div className="mt-3 flex flex-wrap items-center gap-2">
    <button className={button} disabled={busy || !storage.draft || query.isLoading || !!query.error} onClick={() => void upload()}>현재 초안을 서버에 저장</button>
    <button className={button} disabled={busy || !query.data?.payload || !!storage.draft} onClick={download}>서버 초안 불러오기</button>
    <button className={button} disabled={busy || !query.data?.payload} onClick={() => void remove()}>서버 사본 삭제</button>
    <button className={button} disabled={busy} onClick={() => void query.refetch()}>서버 상태 새로고침</button>
    {query.data?.payload && <p className="w-full text-xs text-slate-500">최근 저장: {new Date(query.data.updated_at).toLocaleString("ko-KR")}</p>}
    <p className="w-full text-xs text-slate-500">저장·불러오기는 직접 선택합니다. 다른 기기의 수정과 충돌하면 기존 내용을 덮어쓰지 않습니다.</p>
    {(message || query.error) && <p className="w-full" role="status">{message || workspaceError(query.error)}</p>}
  </div></details>;
}
