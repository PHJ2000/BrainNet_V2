"use client";
import ProjectDialog from "@/features/projects/ProjectDialog";
import type { useGraphEditing } from "./useGraphEditing";

export default function NodeEditor({ editing }: { editing: ReturnType<typeof useGraphEditing> }) {
  const { draft, open, save } = editing;
  if (!open || !draft) return null;
  const busy = save.state.kind === "saving";
  return <ProjectDialog title={draft.mode === "create" ? "자식 노드 작성" : "노드 편집"} busy={busy} onClose={editing.close}>
    <form onSubmit={event => { event.preventDefault(); void editing.submit(); }} className="space-y-4">
      <label className="block text-sm">노드 내용<textarea aria-label="노드 내용" autoFocus rows={8} maxLength={8000} disabled={busy} readOnly={editing.readOnly || save.isBlocked()}
        value={draft.content} onChange={event => editing.change(event.target.value)}
        className="mt-2 w-full resize-y rounded border p-3 leading-6" /></label>
      <p className="text-sm text-slate-500">{editing.persistenceError || "초안은 이 브라우저에 보관됩니다. 닫거나 새로고침한 뒤 이어 쓸 수 있습니다."}</p>
      {["failed", "conflict"].includes(save.state.kind) && <p role="alert" className="text-sm text-red-700">{save.state.message}</p>}
      <div className="flex flex-wrap gap-3">
        <button disabled={editing.readOnly || busy || !draft.content.trim() || save.isBlocked()} className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-40">저장</button>
        {save.state.kind === "failed" && <button type="button" onClick={() => void save.retry()} className="rounded border px-4 py-2">저장 다시 시도</button>}
        {save.state.kind === "conflict" && <button type="button" onClick={() => void editing.readLatest()} className="rounded border px-4 py-2">최신 상태 확인</button>}
        <button type="button" disabled={busy} onClick={editing.discard} className="text-sm text-red-700 underline">초안 버리기</button>
      </div>
      {editing.latest && <div className="rounded bg-slate-50 p-3"><p className="text-sm font-semibold">현재 서버 내용 (초안과 비교)</p><p className="mt-2 whitespace-pre-wrap text-sm">{editing.latest}</p></div>}
    </form>
  </ProjectDialog>;
}
