"use client";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import ProjectDialog from "@/features/projects/ProjectDialog";
import { button, field, primary, priorities, statuses, TaskPayload, useMembers, useWorkspaceList, workspaceError, type Task } from "./api";
import { useWorkspaceDraft } from "./useWorkspaceDraft";
import CloudDraft from "./CloudDraft";
import { TaskDependencies } from "./Collaboration";

export function TaskEditor({ projectId, task, onClose, readOnly = false }: { projectId: number; task: Task; onClose: () => void; readOnly?: boolean }) {
  const [value, setValue] = useState(task), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const storage = useWorkspaceDraft<Task>(projectId, "task");
  const [attempted, setAttempted] = useState(storage.draft?.item.id === task.id && storage.draft.attempted);
  const members = useMembers(projectId), cache = useQueryClient();
  const isNew = task.version < 0;
  const { save: saveDraft } = storage;
  useEffect(() => { if (!readOnly) saveDraft({ item: value, attempted }); }, [value, attempted, readOnly, saveDraft]);
  const update = <K extends keyof Task>(key: K, next: Task[K]) => setValue(current => ({ ...current, [key]: next }));
  const save = async () => {
    if (busy) return;
    setBusy(true); setAttempted(true); setError("");
    storage.save({ item: value, attempted: true });
    try {
      const payload = TaskPayload(value);
      if (isNew) await apiClient.post(`/projects/${projectId}/tasks`, { ...payload, id: task.id });
      else await apiClient.put(`/projects/${projectId}/tasks/${task.id}`, { ...payload, expected_version: value.version });
      storage.discard(); await cache.invalidateQueries({ queryKey: ["workspace", projectId] }); onClose();
    } catch (e) { setError(workspaceError(e)); }
    finally { setBusy(false); }
  };
  return <ProjectDialog title={isNew ? "새 실행 과제" : "실행 과제"} busy={busy} onClose={onClose}>
    <form onSubmit={event => { event.preventDefault(); void save(); }} className="space-y-4">
      <fieldset disabled={readOnly || busy || (isNew && attempted)} className="space-y-4 disabled:opacity-70">
        <label className="block text-sm">과제 제목<input aria-label="과제 제목" className={field} maxLength={240} required value={value.title} onChange={e => update("title", e.target.value)} /></label>
        <label className="block text-sm">완료 조건과 내용<textarea aria-label="완료 조건과 내용" className={field} rows={5} maxLength={12000} value={value.body} onChange={e => update("body", e.target.value)} /></label>
        <div className="grid grid-cols-2 gap-4">
          <label className="text-sm">상태<select aria-label="과제 상태" className={field} value={value.status} onChange={e => update("status", e.target.value as Task["status"])}>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label className="text-sm">우선순위<select className={field} value={value.priority} onChange={e => update("priority", e.target.value as Task["priority"])}>{Object.entries(priorities).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label className="text-sm">담당자<select className={field} value={value.assignee_id ?? ""} onChange={e => update("assignee_id", Number(e.target.value) || null)}><option value="">미지정</option>{members.data?.filter(m => m.role !== "VIEWER").map(m => <option key={m.user_id} value={m.user_id}>{m.email}</option>)}{value.assignee_id && !members.data?.some(m => m.user_id === value.assignee_id) && <option value={value.assignee_id}>이전 담당자 #{value.assignee_id}</option>}</select></label>
          <label className="text-sm">마감일<input type="date" className={field} value={value.due_date ?? ""} onChange={e => update("due_date", e.target.value || null)} /></label>
        </div>
        {value.node_id && <p className="text-xs text-slate-500">연결된 아이디어 #{value.node_id} <button type="button" className="ml-2 underline" onClick={() => update("node_id", null)}>연결 해제</button></p>}
      </fieldset>
      {members.error && <p role="alert">담당자 목록을 불러오지 못했습니다. <button type="button" className="underline" onClick={() => void members.refetch()}>다시 불러오기</button></p>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {!readOnly && <button className={primary} disabled={busy || !value.title.trim()}>{busy ? "저장 중…" : error ? "같은 내용으로 재시도" : "과제 저장"}</button>}
      {!readOnly && <p className="text-xs text-slate-500">브라우저 저장 공간을 사용할 수 있으면 이 탭에 입력 초안을 보관합니다. 닫은 뒤 실행 보드에서 이어쓸 수 있습니다.</p>}
      {error && <button type="button" className={`${button} ml-2`} onClick={() => { void cache.invalidateQueries({ queryKey: ["workspace", projectId] }); onClose(); }}>목록 확인</button>}
    </form>
    {!isNew && <TaskDependencies projectId={projectId} task={value} readOnly={readOnly || busy} onSaved={saved => update("version", saved.version)} />}
  </ProjectDialog>;
}

export function newTask(nodeId: number | null = null, title = ""): Task {
  return { id: uuid(), title: title.slice(0, 240), body: "", status: "TODO", priority: "MEDIUM", assignee_id: null, due_date: null, node_id: nodeId, version: -1, created_at: new Date().toISOString() };
}

export default function TaskBoard({ projectId, readOnly }: { projectId: number; readOnly: boolean }) {
  const [editing, setEditing] = useState<Task | null>(null), [search, setSearch] = useState(""), [assignee, setAssignee] = useState(""), [priority, setPriority] = useState("");
  const query = useWorkspaceList<Task>(projectId, "tasks", { q: search, assignee, priority }), members = useMembers(projectId);
  const [selected, setSelected] = useState<Record<string, number>>({}), [bulkState, setBulkState] = useState("TODO"), [bulkError, setBulkError] = useState(""), [bulkBusy, setBulkBusy] = useState(false);
  const bulk = async () => {
    setBulkBusy(true); setBulkError("");
    try { await apiClient.post(`/projects/${projectId}/tasks/bulk-status`, { tasks: Object.entries(selected).map(([id, expected_version]) => ({ id, expected_version })), status: bulkState }); setSelected({}); await query.refetch(); }
    catch (e) { setBulkError(workspaceError(e)); } finally { setBulkBusy(false); }
  };
  const storage = useWorkspaceDraft<Task>(projectId, "task");
  const rows = query.data?.pages.flatMap(page => page.items) ?? [];
  if (query.error) return <div role="alert">{workspaceError(query.error)} <button className={button} onClick={() => void query.refetch()}>다시 불러오기</button></div>;
  return <section className="space-y-5" aria-label="실행 보드">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-semibold">아이디어를 실행으로</h2><p className="mt-1 text-sm text-slate-500">담당자와 완료 조건을 정하고 진행 상황을 함께 확인하세요.</p></div>{!readOnly && <button className={primary} disabled={!!storage.draft} onClick={() => setEditing(newTask())}>새 과제</button>}</header>
    {!readOnly && storage.draft && <div role="status" className="flex flex-wrap items-center gap-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm"><span>이 탭에 저장된 과제 초안이 있습니다.</span><button className={button} onClick={() => setEditing(storage.draft!.item)}>과제 초안 이어쓰기</button><button className="underline" onClick={storage.discard}>초안 폐기</button></div>}
    {!readOnly && <CloudDraft projectId={projectId} kind="task" />}
    <div className="flex flex-wrap gap-2"><input aria-label="과제 검색" placeholder="전체 과제 제목 검색" className={`${field} !mt-0 !w-60`} value={search} maxLength={200} onChange={e => setSearch(e.target.value)} />
      <select aria-label="담당자 필터" className={button} value={assignee} onChange={e => setAssignee(e.target.value)}><option value="">모든 담당자</option><option value="none">미지정</option>{members.data?.map(m => <option key={m.user_id} value={m.user_id}>{m.email}</option>)}</select>
      <select aria-label="우선순위 필터" className={button} value={priority} onChange={e => setPriority(e.target.value)}><option value="">모든 우선순위</option>{Object.entries(priorities).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
      <button className={button} onClick={() => void query.refetch()}>새로고침</button></div>
    {query.isLoading && <p role="status">과제를 불러오는 중…</p>}
    {!readOnly && <div className="flex flex-wrap items-center gap-2 text-sm"><span>{Object.keys(selected).length}개 선택 · 최대 100개</span><select aria-label="일괄 변경 상태" className={button} value={bulkState} onChange={e => setBulkState(e.target.value)}>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><button className={button} disabled={bulkBusy || !Object.keys(selected).length} onClick={() => void bulk()}>선택 과제 상태 변경</button><button className={button} onClick={() => setSelected({})}>선택 해제</button>{bulkError && <p role="alert">{bulkError}</p>}</div>}
    <div className="grid gap-4 xl:grid-cols-4 sm:grid-cols-2">{Object.entries(statuses).map(([status, label]) => <section key={status} aria-label={label} className="min-h-40 rounded-lg border border-slate-200 bg-slate-50/80 p-3">
      <h3 className="mb-4 flex items-center justify-between text-sm font-semibold"><span>{label}</span><span className="text-slate-500">{rows.filter(row => row.status === status).length}</span></h3>
      <div className="space-y-3">{rows.filter(row => row.status === status).map(task => <div key={task.id}>{!readOnly && <label className="mb-1 flex items-center gap-2 text-xs"><input type="checkbox" aria-label={`선택: ${task.title}`} checked={task.id in selected} disabled={bulkBusy || (!(task.id in selected) && Object.keys(selected).length >= 100)} onChange={e => setSelected(current => { const next = { ...current }; if (e.target.checked) next[task.id] = task.version; else delete next[task.id]; return next; })} />일괄 변경에 포함</label>}<button disabled={!readOnly && !!storage.draft && storage.draft.item.id !== task.id} onClick={() => setEditing(storage.draft?.item.id === task.id ? storage.draft.item : task)} className="block w-full rounded-md border border-slate-200 bg-white p-3 text-left shadow-sm hover:border-indigo-400 focus-visible:outline-2 focus-visible:outline-indigo-600 disabled:opacity-50">
        <p className="mb-3 break-words text-sm font-medium">{task.title}</p><div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500"><span className={task.priority === "HIGH" ? "text-amber-800" : ""}>{priorities[task.priority]}</span>{task.due_date && <time dateTime={task.due_date}>{task.due_date}</time>}</div>
        <p className="mt-2 truncate text-xs text-slate-500">{members.data?.find(m => m.user_id === task.assignee_id)?.email ?? (task.assignee_id ? "이전 담당자" : "담당자 미지정")}</p>
      </button></div>)}{!rows.some(row => row.status === status) && <p className="text-xs text-slate-400">표시할 과제가 없습니다.</p>}</div>
    </section>)}</div>
    {query.hasNextPage && <button className={button} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>검색 결과 더 불러오기</button>}
    {editing && <TaskEditor key={editing.id} projectId={projectId} task={editing} readOnly={readOnly} onClose={() => setEditing(null)} />}
  </section>;
}
