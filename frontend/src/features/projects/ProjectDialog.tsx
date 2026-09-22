"use client";
import { useEffect, useId, useRef, type ReactNode } from "react";

export default function ProjectDialog({ title, children, onClose, busy = false }: {
  title: string; children: ReactNode; onClose: () => void; busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement as HTMLElement | null;
    dialog.showModal();
    return () => { dialog.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} tabIndex={-1} aria-labelledby={titleId} onKeyDown={event => {
    if (event.key !== "Tab") return;
    const dialog = ref.current!;
    const controls = Array.from(dialog.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, summary, [tabindex]"))
      .filter(element => element.tabIndex >= 0 && !element.matches(":disabled, [hidden]") && element.getClientRects().length > 0);
    const first = controls[0], last = controls[controls.length - 1];
    if (!first) { event.preventDefault(); dialog.focus(); }
    else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }} onCancel={event => {
    event.preventDefault(); if (!busy) onClose();
  }} className="m-auto max-h-[90vh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-xl border border-slate-200 bg-white p-6 text-slate-900 shadow-xl backdrop:bg-slate-950/40">
    <header className="mb-5 flex items-center justify-between gap-4">
      <h2 id={titleId} className="text-xl font-semibold">{title}</h2>
      <button type="button" onClick={onClose} disabled={busy} aria-label="닫기" className="rounded px-3 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-40">✕</button>
    </header>
    {children}
  </dialog>;
}
