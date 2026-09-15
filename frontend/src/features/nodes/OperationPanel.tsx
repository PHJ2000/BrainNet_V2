"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { v4 as uuid } from "uuid";
import { confirmDelete, DeletePreview, listOperations, Operation, operationError,
  OperationPreview, previewDelete, previewOperation, undoOperation } from "./operationApi";

const labels = { create: "노드 생성", update: "본문·위치 변경", delete: "가지 삭제", undo: "실행 취소" };
const button = "rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50";

export default function OperationPanel({ projectId, deleteId, closeDelete, refresh }: {
  projectId: number; deleteId: string | null; closeDelete: () => void; refresh: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Operation[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [preview, setPreview] = useState<OperationPreview | null>(null);
  const [deletion, setDeletion] = useState<DeletePreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const key = useRef(uuid());
  const alive = useRef(true);
  const loadSequence = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(async (before?: string) => {
    const sequence = ++loadSequence.current;
    try {
      const page = await listOperations(projectId, before);
      if (!alive.current || sequence !== loadSequence.current) return;
      setItems(prev => before ? [...prev, ...page.items] : page.items);
      setCursor(page.next_cursor);
    } catch (e) { if (alive.current) setError(operationError(e)); }
  }, [projectId]);
  useEffect(() => {
    if (!deleteId) return;
    let cancelled = false;
    void previewDelete(projectId, deleteId).then(p => { if (!cancelled) setDeletion(p); })
      .catch(e => { if (!cancelled) setError(operationError(e)); });
    return () => { cancelled = true; };
  }, [deleteId, projectId]);
  const inspect = async (item: Operation) => {
    setBusy(true); setError("");
    try { const p = await previewOperation(projectId, item.id);
      if (alive.current) { setPreview(p); key.current = uuid(); }
    } catch (e) { if (alive.current) setError(operationError(e)); }
    finally { if (alive.current) setBusy(false); }
  };
  const confirm = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      if (deleteId && deletion) await confirmDelete(projectId, deleteId, deletion, key.current);
      else if (preview) await undoOperation(projectId, preview, key.current);
      else return;
      if (!alive.current) return;
      setPreview(null); setDeletion(null); closeDelete();
      await refresh(); await load();
    } catch (e) { if (alive.current) setError(operationError(e)); }
    finally { if (alive.current) setBusy(false); }
  };
  return <>
    <button className={`${button} absolute right-4 top-4 z-20`} onClick={() => { if (!open) void load(); setOpen(v => !v); setError(""); }}>
      변경 기록
    </button>
    {open && <aside aria-label="노드 변경 기록" className="absolute right-4 top-16 z-20 max-h-[70vh] w-80 overflow-auto rounded-lg border bg-white p-4 shadow-lg">
      <div className="flex items-center justify-between"><h2 className="font-semibold">변경 기록</h2>
        <button className={button} onClick={() => void load()}>새로고침</button></div>
      <p className="my-2 text-xs text-slate-500">자신의 작업을 30일 동안 되돌릴 수 있어요. 기능 적용 전 기록과 AI 생성은 포함하지 않아요.</p>
      {!items.length && <p className="py-4 text-sm">기록된 작업이 없어요.</p>}
      <ol className="divide-y">{items.map(item => <li key={item.id} className="py-3 text-sm">
        <div>{labels[item.kind]} · 노드 {item.node_id}</div>
        <div className="text-xs text-slate-500">사용자 {item.actor_id ?? "삭제됨"} · {new Date(item.created_at).toLocaleString()}</div>
        <button className={`${button} mt-2`} disabled={!item.can_undo || busy} onClick={() => void inspect(item)}>
          {item.expired ? "보존 기간 만료" : item.undone_by ? "취소 완료" : item.can_undo ? "되돌리기 미리보기" : "취소할 수 없음"}
        </button>
      </li>)}</ol>
      {cursor && <button className={button} onClick={() => void load(cursor)}>이전 기록 더 보기</button>}
    </aside>}
    {(preview || deleteId) && <div className="absolute inset-0 z-40 flex items-center justify-center bg-slate-900/30 p-4">
      <section role="dialog" aria-modal="true" aria-label={deleteId ? "가지 삭제 미리보기" : "실행 취소 미리보기"}
        className="max-h-[80vh] w-full max-w-lg overflow-auto rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-lg font-semibold">{deleteId ? "가지 삭제" : "실행 취소"} 미리보기</h2>
        <p className="my-3 text-sm text-slate-600">{deleteId ? `${deletion?.node_count ?? "…"}개 노드와 태그 연결을 삭제해요. 변경 기록에서 30일 동안 복구할 수 있어요.` : "다른 작업과 충돌하면 적용하지 않아요. 아래 내용을 확인해 주세요."}</p>
        {preview && <div className="grid grid-cols-2 gap-3 text-sm">
          <div><h3 className="font-medium">되돌리기 전</h3>{preview.after.nodes?.map(n => <div key={n.id}><p className="whitespace-pre-wrap break-words">{n.content}</p><p className="text-xs text-slate-500">위치 ({n.pos_x ?? 0}, {n.pos_y ?? 0})</p></div>) ?? "삭제된 상태"}</div>
          <div><h3 className="font-medium">되돌린 후</h3>{preview.before.nodes?.map(n => <div key={n.id}><p className="whitespace-pre-wrap break-words">{n.content}</p><p className="text-xs text-slate-500">위치 ({n.pos_x ?? 0}, {n.pos_y ?? 0})</p></div>) ?? "노드 삭제"}</div>
        </div>}
        {deletion && <ul className="max-h-48 overflow-auto text-sm">{deletion.nodes.map(n => <li key={n.id} className="whitespace-pre-wrap break-words">{n.content}</li>)}</ul>}
        {error && <p role="alert" className="my-3 text-sm text-red-700">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button className={button} disabled={busy} onClick={() => { setPreview(null); setDeletion(null); closeDelete(); setError(""); }}>닫기</button>
          <button className={button} disabled={busy || (!!deleteId && !deletion)} onClick={() => void confirm()}>{busy ? "처리 중…" : deleteId ? "가지 삭제 확인" : "실행 취소 확인"}</button>
        </div>
      </section>
    </div>}
    {error && !preview && !deleteId && <p role="alert" className="absolute right-4 top-16 z-30 max-w-sm rounded border bg-white p-3 text-sm text-red-700" onClick={() => setError("")}>{error}</p>}
  </>;
}
