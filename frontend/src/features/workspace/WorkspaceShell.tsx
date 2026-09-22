"use client";
import { useState } from "react";
import { usePathname } from "next/navigation";
import Sidebar from "@/app/components/Sidebar";

export default function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [openPath, setOpenPath] = useState<string | null>(null);
  const open = openPath === path;
  return <div className="flex h-dvh w-full flex-col bg-white text-slate-900 md:flex-row">
    <header className="flex shrink-0 items-center justify-between border-b px-4 py-3 md:hidden"><span className="font-semibold">BrainNet</span><button aria-expanded={open} aria-controls="workspace-navigation" className="rounded border px-3 py-1 text-sm" onClick={() => setOpenPath(open ? null : path)}>{open ? "메뉴 닫기" : "프로젝트 메뉴"}</button></header>
    <aside id="workspace-navigation" className={`${open ? "flex max-h-[45vh]" : "hidden"} shrink-0 flex-col border-r border-slate-200 bg-slate-50 md:flex md:max-h-none md:w-60`}>
      <div className="hidden border-b border-slate-200 px-6 py-6 md:block"><span className="text-xl font-semibold tracking-tight text-indigo-800">BrainNet</span><p className="mt-1 text-xs text-slate-500">아이디어에서 실행까지</p></div>
      <div className="min-h-0 flex-1 overflow-y-auto py-2"><Sidebar /></div>
    </aside>
    <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
  </div>;
}
