// app/components/Sidebar.tsx
"use client";

import { useProjects } from "@/features/projects/useProjects";
import Link from "next/link";
import { Plus } from "lucide-react";
import { useState } from "react";
import type { Project } from "@/types/api";
import ProjectFormModal from "./ProjectFormModal";

export default function Sidebar() {
  const { data: projects = [], isLoading } = useProjects();
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <div className="flex flex-col h-full p-4">
      <h2 className="text-lg font-bold mb-4">내 프로젝트</h2>

      <div className="flex-1 space-y-2 overflow-y-auto">
        {/* 프로젝트 목록 */}
        {isLoading ? (
          <div className="text-sm text-gray-400">불러오는 중...</div>
        ) : (
          projects.map((p: Project) => (
            <Link
              key={p.id}
              href={`/dashboard/projects/${p.id}`}
              className="block text-sm text-gray-700 hover:text-black px-2 py-1 rounded hover:bg-gray-100"
            >
              {p.name}
            </Link>
          ))
        )}

        {/* + 버튼도 같은 목록 안에 배치 */}
        <button
          onClick={() => setModalOpen(true)}
          className="flex items-center justify-center w-full text-sm font-bold text-white bg-gradient-to-r from-blue-600 to-purple-500 py-2 mt-4 rounded-xl shadow hover:from-blue-700 hover:to-purple-700 transition-all"
        >
          <Plus size={18} className="mr-2" />
          새 프로젝트
        </button>
      </div>

      {/* 모달 */}
      {modalOpen && <ProjectFormModal onClose={() => setModalOpen(false)} />}
    </div>
  );
}
