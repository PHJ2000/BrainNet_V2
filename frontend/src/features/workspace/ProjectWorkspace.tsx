"use client";
import { useCallback, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useNodeEvents } from "@/features/nodes/useNodeEvents";
import Graph from "@/features/nodes/Graph";
import type { Project } from "@/types/api";
import TaskBoard from "./TaskBoard";
import KnowledgeLibrary from "./KnowledgeLibrary";
import Discussions from "./Discussions";
import AIReview from "./AIReview";
import WorkspaceExport from "./WorkspaceExport";
import { button, useMembers, useWorkspaceList, workspaceError, type Knowledge } from "./api";

const tabs = { graph: "아이디어 맵", tasks: "실행 보드", knowledge: "지식", discussions: "토론", ai: "AI 검토", activity: "활동" };
type Tab = keyof typeof tabs;
type Activity = { id: number; kind: string; actor_id: number | null; target_id: string; created_at: string };
const kinds: Record<string, string> = { "task.created": "과제 생성", "task.updated": "과제 수정", "discussion.created": "토론 작성", "discussion.updated": "토론 수정", "proposal.requested": "AI 검토 요청", "proposal.finished": "AI 검토 완료", "proposal.accepted": "AI 제안 채택", "project.restored": "프로젝트 복원" };

function ActivityFeed({ projectId }: { projectId: number }) {
  const query = useWorkspaceList<Activity>(projectId, "activity"), members = useMembers(projectId);
  return <section className="space-y-4"><h2 className="text-xl font-semibold">작업 공간 활동</h2><p className="text-sm text-slate-500">과제·토론·AI 검토의 변경 기록입니다. 노드 변경과 실행 취소는 아이디어 맵의 작업 이력에서 확인하세요.</p>
    {query.isLoading && <p role="status">활동을 불러오는 중…</p>}{query.error ? <p role="alert">{workspaceError(query.error)}</p> : <ul className="divide-y border-y border-slate-200">{query.data?.pages.flatMap(page => page.items).map(row => <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm"><span>{kinds[row.kind] ?? row.kind} <span className="ml-3 text-slate-500">{members.data?.find(m => m.user_id === row.actor_id)?.email ?? "이전 멤버"}</span></span><time className="text-xs text-slate-500">{new Date(row.created_at).toLocaleString("ko-KR")}</time></li>)}</ul>}
    {!query.isLoading && !query.error && !query.data?.pages[0].items.length && <p className="text-sm text-slate-500">아직 활동이 없습니다.</p>}
    {query.hasNextPage && <button className={button} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>이전 활동 더 보기</button>}
  </section>;
}

function LiveWorkspace({ projectId, children }: { projectId: number; children: React.ReactNode }) {
  const cache = useQueryClient();
  const reload = useCallback(async () => { await Promise.all([
    cache.invalidateQueries({ queryKey: ["workspace", projectId] }), cache.invalidateQueries({ queryKey: ["knowledge"] }),
    cache.invalidateQueries({ queryKey: ["project", projectId] }),
  ]); }, [cache, projectId]);
  const { accessError, connection } = useNodeEvents(projectId, reload);
  return <div className="h-full overflow-y-auto p-4 sm:p-6"><div className="mx-auto max-w-6xl"><div className="mb-4 text-right text-xs text-slate-400" aria-live="polite">{connection}</div>{accessError ? <p role="alert">{accessError}</p> : children}</div></div>;
}

export default function ProjectWorkspace({ project }: { project: Project }) {
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(params.get("view") === "discussions" ? "discussions" : "graph"), [selected, setSelected] = useState<Knowledge[]>([]), [message, setMessage] = useState("");
  const projectId = Number(project.id), readOnly = project.my_role === "VIEWER";
  const select = (node: Knowledge) => {
    if (selected.some(item => item.id === node.id)) { setMessage("이미 선택한 아이디어입니다."); return; }
    if (selected.length >= 8) { setMessage("한 번에 8개까지 선택할 수 있습니다."); return; }
    setSelected(current => [...current, node]); setMessage("AI 검토에 추가했습니다. AI 검토 화면에서 요청을 시작하세요.");
  };
  return <div className="flex min-h-0 flex-1 flex-col">
    <nav aria-label="프로젝트 보기" className="flex shrink-0 gap-1 overflow-x-auto border-b border-slate-200 px-4 sm:px-6">{Object.entries(tabs).map(([key, label]) => <button key={key} aria-current={tab === key ? "page" : undefined} onClick={() => { setTab(key as Tab); setMessage(""); }} className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-indigo-600 ${tab === key ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-900"}`}>{label}{key === "ai" && selected.length > 0 ? ` (${selected.length})` : ""}</button>)}</nav>
    {message && <p role="status" className="bg-indigo-50 px-6 py-2 text-sm text-indigo-800">{message}</p>}
    <div className="min-h-0 flex-1">{tab === "graph" ? <Graph projectId={projectId} readOnly={readOnly} aiEnabled={project.ai_enabled} /> : <LiveWorkspace projectId={projectId}>
      {tab === "tasks" && <TaskBoard projectId={projectId} readOnly={readOnly} />}
      {tab === "knowledge" && <KnowledgeLibrary projectId={projectId} readOnly={readOnly} onSelectAI={select} />}
      {tab === "discussions" && <Discussions projectId={projectId} readOnly={readOnly} owner={project.my_role === "OWNER"} initialThread={params.get("thread")} />}
      {tab === "ai" && <AIReview projectId={projectId} readOnly={readOnly} owner={project.my_role === "OWNER"} enabled={!!project.ai_enabled} selected={selected} onRemove={id => setSelected(rows => rows.filter(row => row.id !== id))} onPick={() => setTab("knowledge")} />}
      {tab === "activity" && <ActivityFeed projectId={projectId} />}
    </LiveWorkspace>}</div>
    <WorkspaceExport projectId={projectId} />
  </div>;
}
