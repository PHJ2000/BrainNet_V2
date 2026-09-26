// app/components/Sidebar.tsx
"use client";

import { useProjects } from "@/features/projects/useProjects";
import Link from "next/link";
import { Plus, Search, X } from "lucide-react";
import { useRef, useState } from "react";
import type { Project } from "@/types/api";
import ProjectFormModal from "./ProjectFormModal";

export default function Sidebar() {
  const { data: projects = [], isLoading, isError } = useProjects();
  const [modalOpen, setModalOpen] = useState(false);
  const [search, setSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const query = search.trim().toLowerCase();
  const filteredProjects = projects.filter((project: Project) =>
    project.name.toLowerCase().includes(query)
  );

  return (
    <div className="flex flex-col h-full p-4">
      <h2 className="text-lg font-bold mb-4">내 프로젝트</h2>

      <div className="relative mb-4">
        <label htmlFor="project-search" className="sr-only">프로젝트 이름 검색</label>
        <Search aria-hidden="true" size={16} className="absolute left-3 top-3 text-gray-400" />
        <input
          ref={searchInput}
          id="project-search"
          type="text"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="프로젝트 이름 검색"
          className="w-full rounded-lg border border-gray-200 bg-white py-2 pl-9 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
        {search && (
          <button
            type="button"
            aria-label="프로젝트 검색 초기화"
            onClick={() => {
              setSearch("");
              searchInput.current?.focus();
            }}
            className="absolute right-1 top-1 rounded-md p-2 text-gray-500 hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-blue-400"
          >
            <X aria-hidden="true" size={16} />
          </button>
        )}
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto">
        {/* 프로젝트 목록 */}
        {isLoading ? (
          <div className="text-sm text-gray-400">불러오는 중...</div>
        ) : isError ? (
          <div role="alert" className="text-sm text-red-600">프로젝트를 불러오지 못했어요.</div>
        ) : filteredProjects.length === 0 ? (
          <div role="status" className="text-sm text-gray-500">
            {query ? "검색 결과가 없어요." : "아직 프로젝트가 없어요."}
          </div>
        ) : (
          filteredProjects.map((p: Project) => (
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
