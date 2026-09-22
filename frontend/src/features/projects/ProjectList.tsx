"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useProjects } from "./useProjects";
import { projectError } from "./projectError";

export default function ProjectList() {
  const { data: projects, isLoading, error, refetch, isFetching } = useProjects();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const results = useMemo(() => {
    const term = search.normalize("NFC").trim().toLocaleLowerCase();
    return (projects ?? []).filter(p => p.name.normalize("NFC").toLocaleLowerCase().includes(term))
      .sort((a, b) => sort === "name" ? a.name.localeCompare(b.name, "ko") || Number(a.id) - Number(b.id)
        : (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0) || Number(b.id) - Number(a.id));
  }, [projects, search, sort]);
  if (isLoading) return <p role="status">프로젝트를 불러오는 중…</p>;
  if (error) return <div role="alert"><p>{projectError(error)}</p>
    <button disabled={isFetching} onClick={() => void refetch()} className="mt-3 rounded border px-3 py-2">프로젝트 다시 불러오기</button></div>;
  if (!projects?.length) return <p>생성된 프로젝트가 없습니다.</p>;
  return <section aria-label="프로젝트 목록" className="space-y-4">
    <div className="flex flex-wrap gap-3">
      <input aria-label="프로젝트 이름 검색" type="search" value={search} onChange={e => setSearch(e.target.value)}
        placeholder="프로젝트 이름 검색" className="min-w-48 flex-1 rounded border bg-white px-3 py-2" />
      <select aria-label="프로젝트 정렬" value={sort} onChange={e => setSort(e.target.value)} className="rounded border bg-white px-3 py-2">
        <option value="newest">최근 생성순</option><option value="name">이름순</option>
      </select>
    </div>
    <p role="status" className="text-sm text-slate-600">{results.length}개 프로젝트</p>
    {!results.length && <p>검색 조건에 맞는 프로젝트가 없습니다.</p>}
    {results.map(project => <Link key={project.id} href={`/dashboard/projects/${project.id}`}
      className="block rounded border p-4 hover:bg-indigo-50 focus-visible:outline-indigo-600">
      <h2 className="font-semibold">{project.name}</h2><p className="text-sm text-slate-600">{project.description}</p>
    </Link>)}
  </section>;
}
