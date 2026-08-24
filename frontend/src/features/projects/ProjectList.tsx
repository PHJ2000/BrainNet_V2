// // features/projects/ProjectList.tsx
// import Link from "next/link";
// import { useProjects } from "./useProjects";

// export default function ProjectList() {
//   const { data: projects, isLoading } = useProjects();

//   if (isLoading) return <p>로딩 중...</p>;

//   return (
//     <div className="grid gap-4">
//       {projects?.map((p) => (
//         <Link
//           key={p.id}
//           href={`/project/${p.id}`}
//           className="border p-4 rounded hover:bg-gray-50"
//         >
//           <h3 className="text-lg font-semibold">{p.name}</h3>
//           <p className="text-sm text-gray-500">{p.description}</p>
//         </Link>
//       ))}
//     </div>
//   );
// }

// features/projects/ProjectList.tsx
"use client";

import { useProjects } from "./useProjects";
import Link from "next/link";
import type { Project } from "@/types/api";

export default function ProjectList() {
  const { data: projects, isLoading } = useProjects();


  if (isLoading) return <div>Loading...</div>;
  if (!projects?.length) return <div>생성된 프로젝트가 없습니다.</div>;

  return (
    <div className="space-y-4">
      {projects.map((project: Project) => (
        <Link key={project.id} href={`/dashboard/projects/${project.id}`}>
          <div className="p-4 border rounded hover:bg-gray-100 cursor-pointer">
            <h2 className="font-semibold">{project.name}</h2>
            <p className="text-sm text-gray-500">{project.description}</p>
          </div>
        </Link>
      ))}
    </div>
  );
}
