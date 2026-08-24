// app/(main)/dashboard/projects/[projectId]/page.tsx
"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/apiClient";
import Graph from "@/features/nodes/Graph";
import type { Project } from "@/types/api";

export default function ProjectDetailPage() {
  // 👉 useParams() 값은 항상 **문자열**
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);        // ← 숫자로 변환
  const [project, setProject] = useState<Project | null>(null);

  useEffect(() => {
    const fetch = async () => {
      const { data } = await apiClient.get(`/projects/${pid}`);
      setProject(data);
    };
    fetch();
  }, [pid]);

  if (!project) return <div>로딩 중...</div>;

  return (
    <div className="h-full w-full flex flex-col"
    style={{
    backgroundImage: 'linear-gradient(135deg, #f0f4ff 0%, #f9fafe 100%)',
  }}>
      <h1
  className="text-4xl font-bold text-transparent text-center px-6 py-4 bg-clip-text drop-shadow-md"
  style={{
    backgroundImage: 'linear-gradient(135deg, #2563eb, #7c3aed)',
  }}
>
        {project.name}
      </h1>
      {/* <p className="text-sm text-gray-600 mb-4 leading-relaxed">
        {project.description}
      </p> */}
      <div className="flex-1 min-h-0">  {/* ⬅️ 여기서 그래프가 flex-1로 꽉 차도록! */}
        <Graph projectId={Number(project.id)} />
      </div>
    </div>
  );
}
