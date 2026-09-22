// app/(main)/dashboard/projects/[projectId]/page.tsx
"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";
import Graph from "@/features/nodes/Graph";
import type { Project } from "@/types/api";
import ProjectSettings from "@/features/projects/ProjectSettings";

export default function ProjectDetailPage() {
  // 👉 useParams() 값은 항상 **문자열**
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);        // ← 숫자로 변환
  const validId = Number.isSafeInteger(pid) && pid > 0;
  const { data: project, isError, refetch } = useQuery({
    queryKey: ["project", pid],
    enabled: validId,
    queryFn: async ({ signal }) => {
      const { data } = await apiClient.get<Project>(`/projects/${pid}`, { signal });
      return data;
    },
    retry: false,
  });
  if (!validId || isError) return <div role="alert" className="p-6">
    <p>프로젝트를 불러올 수 없습니다. 삭제 여부와 접근 권한을 확인해 주세요.</p>
    {validId && <button onClick={() => void refetch()} className="mt-3 rounded border px-3 py-2">다시 시도</button>}
  </div>;
  if (!project) return <div>로딩 중...</div>;

  return (
    <div className="h-full w-full flex flex-col"
    style={{
    backgroundImage: 'linear-gradient(135deg, #f0f4ff 0%, #f9fafe 100%)',
  }}>
      <header className="flex items-center justify-between gap-4 px-6">
      <h1
  className="text-4xl font-bold text-transparent text-center px-6 py-4 bg-clip-text drop-shadow-md"
  style={{
    backgroundImage: 'linear-gradient(135deg, #2563eb, #7c3aed)',
  }}
>
        {project.name}
      </h1>
      <ProjectSettings key={project.id} project={project} />
      </header>
      {/* <p className="text-sm text-gray-600 mb-4 leading-relaxed">
        {project.description}
      </p> */}
      <div className="flex-1 min-h-0">  {/* ⬅️ 여기서 그래프가 flex-1로 꽉 차도록! */}
        <Graph key={project.id} projectId={Number(project.id)} />
      </div>
    </div>
  );
}
