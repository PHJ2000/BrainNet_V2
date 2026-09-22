// app/components/Sidebar.tsx
"use client";

import { useProjects } from "@/features/projects/useProjects";
import Link from "next/link";
import { Plus } from "lucide-react";
import { useState } from "react";
import type { Project } from "@/types/api";
import ProjectFormModal from "./ProjectFormModal";
import JoinProjectDialog from "@/features/projects/JoinProjectDialog";

export default function Sidebar() {
  const { data: projects = [], isLoading, error, refetch } = useProjects();
  const [modalOpen, setModalOpen] = useState(false);
  const [joinOpen, setJoinOpen] = useState(false);

  return (
    <div className="flex flex-col h-full p-4">
      <Link href="/dashboard" className="mb-4 block text-lg font-semibold hover:text-indigo-700">내 프로젝트</Link>

      <div className="flex-1 space-y-2 overflow-y-auto">
        {/* 프로젝트 목록 */}
        {isLoading ? (
          <div className="text-sm text-gray-400">불러오는 중...</div>
        ) : error ? <button onClick={() => void refetch()} className="text-sm text-red-700">목록을 불러오지 못했습니다. 다시 시도</button> : (
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
          className="flex items-center justify-center w-full text-sm font-medium text-white bg-indigo-700 py-2 mt-4 rounded-md hover:bg-indigo-800"
        >
          <Plus size={18} className="mr-2" />
          새 프로젝트
        </button>
        <button onClick={() => setJoinOpen(true)} className="mt-2 w-full rounded-md border border-slate-300 py-2 text-sm text-slate-700 hover:bg-slate-50">초대 코드로 참여</button>
      </div>

      <button onClick={() => { localStorage.removeItem("token"); window.location.replace("/login"); }} className="mt-4 border-t border-slate-200 pt-3 text-left text-sm text-slate-500 hover:text-slate-900">로그아웃</button>

      {/* 모달 */}
      {modalOpen && <ProjectFormModal onClose={() => setModalOpen(false)} />}
      {joinOpen && <JoinProjectDialog onClose={() => setJoinOpen(false)} />}
    </div>
  );
}
