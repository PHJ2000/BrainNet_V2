// app/(main)/dashboard/page.tsx
"use client";

import { useState } from "react";
import ProjectFormModal from "../../components/ProjectFormModal";
import BackupImport from "@/features/projects/BackupImport";
import ProjectList from "@/features/projects/ProjectList";
import KnowledgeLibrary from "@/features/workspace/KnowledgeLibrary";
import ProjectTrash from "@/features/workspace/ProjectTrash";
import { AssetList } from "@/features/workspace/PersonalAssets";


export default function DashboardPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [view, setView] = useState("projects");
  return (
    <div className="h-full overflow-auto p-8">
      <div className="mx-auto max-w-4xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
      <div><h1 className="text-2xl font-bold text-slate-800">내 프로젝트</h1>
      <p className="mt-1 text-sm text-slate-600">작업할 프로젝트를 찾고 아이디어를 이어가세요.</p></div>
      <button
        type="button"
        onClick={() => setModalOpen(true)}
        className="px-6 py-2 rounded-md bg-indigo-700 text-white font-medium hover:bg-indigo-800"
      >
        + 새 프로젝트 만들기
      </button>
      </header>
      <nav aria-label="대시보드 보기" className="flex gap-4 border-b border-slate-200">
        <button className="px-2 py-3 text-sm" aria-current={view === "projects" ? "page" : undefined} onClick={() => setView("projects")}>프로젝트</button>
        <button className="px-2 py-3 text-sm" aria-current={view === "knowledge" ? "page" : undefined} onClick={() => setView("knowledge")}>전체 지식 검색</button>
      </nav>
      {view === "projects" ? <ProjectList /> : <KnowledgeLibrary />}
      {modalOpen && <ProjectFormModal onClose={() => setModalOpen(false)} />}
      <div className="mt-4"><BackupImport /></div>
      <AssetList kind="TEMPLATE" />
      <ProjectTrash />
      </div>
    </div>
  );
}
