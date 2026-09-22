// app/(main)/dashboard/page.tsx
"use client";

import { useState } from "react";
import ProjectFormModal from "../../components/ProjectFormModal";
import BackupImport from "@/features/projects/BackupImport";
import ProjectList from "@/features/projects/ProjectList";


export default function DashboardPage() {
  const [modalOpen, setModalOpen] = useState(false);
  return (
    <div className="h-full overflow-auto p-8">
      <div className="mx-auto max-w-4xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
      <div><h1 className="text-2xl font-bold text-slate-800">내 프로젝트</h1>
      <p className="mt-1 text-sm text-slate-600">작업할 프로젝트를 찾고 아이디어를 이어가세요.</p></div>
      <button
        type="button"
        onClick={() => setModalOpen(true)}
        className="px-6 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold shadow hover:brightness-110 transition"
      >
        + 새 프로젝트 만들기
      </button>
      </header>
      <ProjectList />
      {modalOpen && <ProjectFormModal onClose={() => setModalOpen(false)} />}
      <div className="mt-4"><BackupImport /></div>
      </div>
    </div>
  );
}
