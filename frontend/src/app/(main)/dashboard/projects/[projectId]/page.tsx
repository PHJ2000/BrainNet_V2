// app/(main)/dashboard/projects/[projectId]/page.tsx
"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";
import ProjectWorkspace from "@/features/workspace/ProjectWorkspace";
import type { Project } from "@/types/api";
import ProjectSettings from "@/features/projects/ProjectSettings";
import { projectError } from "@/features/projects/projectError";

export default function ProjectDetailPage() {
  // 👉 useParams() 값은 항상 **문자열**
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);        // ← 숫자로 변환
  const validId = Number.isSafeInteger(pid) && pid > 0;
  const { data: project, error, isError, refetch, isFetching } = useQuery({
    queryKey: ["project", pid],
    enabled: validId,
    queryFn: async ({ signal }) => {
      const { data } = await apiClient.get<Project>(`/projects/${pid}`, { signal });
      return data;
    },
    retry: false,
  });
  useEffect(() => {
    const refresh = () => { void refetch(); };
    window.addEventListener("brainnet:membership", refresh);
    return () => window.removeEventListener("brainnet:membership", refresh);
  }, [refetch]);
  if (!validId || isError) return <div role="alert" className="p-6">
    <p>{validId ? projectError(error) : "올바르지 않은 프로젝트 주소입니다."}</p>
    {validId && <button disabled={isFetching} onClick={() => void refetch()} className="mt-3 rounded border px-3 py-2">다시 시도</button>}
  </div>;
  if (!project) return <div>로딩 중...</div>;

  return <div className="flex h-full min-w-0 flex-col bg-white text-slate-900">
    <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
      <div className="min-w-0"><h1 className="truncate text-2xl font-semibold">{project.name}</h1>
      {project.description && <p className="mt-1 line-clamp-2 text-sm text-slate-500">{project.description}</p>}</div>
      <ProjectSettings key={project.id} project={project} />
    </header>
    <ProjectWorkspace key={project.id} project={project} />
  </div>;
}
