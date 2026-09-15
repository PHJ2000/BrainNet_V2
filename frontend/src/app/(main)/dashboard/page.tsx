// app/(main)/dashboard/page.tsx
"use client";

import { useState } from "react";
import ProjectFormModal from "../../components/ProjectFormModal";
import BackupImport from "@/features/projects/BackupImport";


export default function DashboardPage() {
  const [modalOpen, setModalOpen] = useState(false);
  return (
    <div className="h-full flex flex-col items-center justify-center py-28">
      {/* 아이콘(원하면 삭제해도 됨) */}
      <div className="mb-4">
        <span className="text-5xl">💡</span>
      </div>
      <h2 className="text-2xl font-bold mb-2 text-gray-700">환영합니다!</h2>
      <p className="text-gray-500 mb-7 text-lg text-center">
        왼쪽에서 프로젝트를 선택하거나<br/>
        새로운 프로젝트를 만들어 <span className="text-blue-500 font-semibold">아이디어</span>를 시작해보세요.
      </p>
      <button
        type="button"
        onClick={() => setModalOpen(true)}
        className="px-6 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold shadow hover:brightness-110 transition"
      >
        + 새 프로젝트 만들기
      </button>
      {modalOpen && <ProjectFormModal onClose={() => setModalOpen(false)} />}
      <div className="mt-4"><BackupImport /></div>
    </div>
  );
}
