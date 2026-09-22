"use client";
import { useState } from "react";
import Link from "next/link";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import { button, field, statuses, priorities, workspaceError, type Task, type ChecklistItem, type Page } from "./api";

export function localDay() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function ChecklistEditor({ items, onChange }: { items: ChecklistItem[]; onChange: (items: ChecklistItem[]) => void }) {
  return <section aria-label="과제 체크리스트" className="space-y-3 border-t border-slate-200 pt-4">
    <h3 className="text-sm font-semibold">체크리스트 · {items.filter(item => item.done).length}/{items.length}</h3>
    {items.map((item, index) => <div key={item.id} className="flex items-center gap-2">
      <input type="checkbox" aria-label={`체크리스트 ${index + 1} 완료`} checked={item.done} onChange={e => onChange(items.map(row => row.id === item.id ? { ...row, done: e.target.checked } : row))} />
      <input aria-label={`체크리스트 ${index + 1} 내용`} className={`${field} !mt-0 min-w-0 flex-1`} required maxLength={240} value={item.text} onChange={e => onChange(items.map(row => row.id === item.id ? { ...row, text: e.target.value } : row))} />
      <button type="button" className="shrink-0 p-2 text-sm underline" aria-label={`체크리스트 ${index + 1} 삭제`} onClick={() => onChange(items.filter(row => row.id !== item.id))}>삭제</button>
    </div>)}
    <button type="button" className={button} disabled={items.length >= 50} onClick={() => onChange([...items, { id: uuid(), text: "", done: false }])}>체크 항목 추가</button>
    <p className="text-xs text-slate-500">모든 항목을 체크하면 과제를 완료할 수 있습니다. 최대 50개.</p>
  </section>;
}

type PersonalTask = Task & { project_id: number; project_name: string; blocked: boolean };
export function MyWork() {
  const [scope, setScope] = useState("assigned"), [due, setDue] = useState("all"), [status, setStatus] = useState("open");
  const [q, setQ] = useState(""), [today, setToday] = useState(localDay), [blocked, setBlocked] = useState(false);
  const query = useInfiniteQuery({ queryKey: ["my-work", scope, due, status, q, today, blocked], initialPageParam: null as string | null,
    queryFn: async ({ pageParam, signal }) => (await apiClient.get<Page<PersonalTask>>("/workspace/tasks", { signal, params: { scope, due, status, q, today, blocked, before: pageParam } })).data,
    getNextPageParam: page => page.next_cursor as string | null, retry: false });
  return <section aria-label="내 작업함" className="space-y-5">
    <header><h2 className="text-xl font-semibold">내 작업함</h2><p className="mt-1 text-sm text-slate-500">참여 중인 프로젝트의 과제를 마감일 순서로 확인하세요.</p></header>
    <div className="flex flex-wrap gap-3">
      <label className="text-sm">범위<select aria-label="작업 범위" className={field} value={scope} onChange={e => setScope(e.target.value)}><option value="assigned">내 담당</option><option value="created">내가 만든 과제</option><option value="all">참여 프로젝트 전체</option></select></label>
      <label className="text-sm">마감<select aria-label="마감 필터" className={field} value={due} onChange={e => setDue(e.target.value)}><option value="all">모든 기한</option><option value="overdue">기한 초과</option><option value="today">오늘</option><option value="week">오늘부터 7일</option><option value="none">기한 없음</option></select></label>
      <label className="text-sm">상태<select aria-label="작업 상태" className={field} value={status} onChange={e => setStatus(e.target.value)}><option value="open">미완료</option><option value="all">모든 상태</option>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="text-sm">기준일<input type="date" aria-label="작업 기준일" className={field} value={today} required onChange={e => { if (e.target.value) setToday(e.target.value); }} /></label>
    </div>
    <div className="flex flex-wrap items-center gap-3"><input aria-label="전체 과제 검색" className={`${field} !mt-0 !w-60 max-w-full`} placeholder="과제 제목 검색" maxLength={200} value={q} onChange={e => setQ(e.target.value)} /><label className="flex gap-2 text-sm"><input type="checkbox" checked={blocked} onChange={e => setBlocked(e.target.checked)} />선행 과제로 막힌 과제만</label><button className={button} onClick={() => void query.refetch()}>새로고침</button></div>
    {query.error && <p role="alert">{workspaceError(query.error)}</p>}{query.isLoading && <p role="status">과제를 불러오는 중…</p>}
    <ul className="divide-y border-y border-slate-200">{query.data?.pages.flatMap(page => page.items).map(task => <li key={task.id} className="space-y-2 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><Link className="min-w-0 break-words font-medium text-indigo-700 underline" href={`/dashboard/projects/${task.project_id}?view=tasks&task=${task.id}`}>{task.title}</Link><span className="text-xs text-slate-500">{statuses[task.status]} · {priorities[task.priority]}</span></div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500"><span>{task.project_name}</span><span className={task.due_date && task.due_date < today && ["TODO", "DOING"].includes(task.status) ? "text-red-700" : ""}>{task.due_date ? `마감 ${task.due_date}` : "기한 없음"}</span>{task.blocked && <span className="text-amber-800">선행 과제 대기</span>}{!!task.checklist?.length && <span>체크 {task.checklist.filter(row => row.done).length}/{task.checklist.length}</span>}{task.repeat_every_days && <span>{task.repeat_every_days}일마다 반복</span>}</div>
    </li>)}</ul>
    {!query.isLoading && !query.error && !query.data?.pages[0].items.length && <p className="text-sm text-slate-500">이 조건에 맞는 과제가 없습니다.</p>}
    {query.hasNextPage && <button className={button} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>과제 더 보기</button>}
  </section>;
}

type Overview = { counts: Record<string, number>; workload: { assignee_id: number | null; email: string | null; open: number; overdue: number }[]; workload_has_more: boolean; upcoming: Task[] };
export function ProjectOverview({ projectId }: { projectId: number }) {
  const [today, setToday] = useState(localDay);
  const query = useQuery({ queryKey: ["workspace", projectId, "overview", today], retry: false,
    queryFn: async ({ signal }) => (await apiClient.get<Overview>(`/projects/${projectId}/overview`, { signal, params: { today } })).data });
  const counts = query.data?.counts, denominator = counts ? counts.total - counts.canceled : 0;
  return <section aria-label="프로젝트 현황" className="space-y-6">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-xl font-semibold">프로젝트 현황</h2><p className="mt-1 text-sm text-slate-500">전체 과제 기준입니다. 취소된 과제는 완료율에서 제외합니다.</p></div><label className="text-sm">기준일<input type="date" className={field} aria-label="현황 기준일" value={today} onChange={e => { if (e.target.value) setToday(e.target.value); }} /></label></header>
    <button className={button} onClick={() => void query.refetch()}>현황 새로고침</button>
    {query.error && <p role="alert">{workspaceError(query.error)}</p>}{query.isLoading && <p role="status">현황을 집계하는 중…</p>}
    {counts && <><div className="border-y border-slate-200 py-5"><p className="mb-3 text-lg font-semibold">완료율 {denominator ? Math.round(counts.done / denominator * 100) : 0}% · {counts.done}/{denominator}</p><progress aria-label="과제 완료율" className="h-2 w-full accent-indigo-700" max={denominator || 1} value={counts.done} /><dl className="mt-5 flex flex-wrap gap-x-8 gap-y-4">{[["전체", "total"], ["할 일", "todo"], ["진행 중", "doing"], ["완료", "done"], ["취소", "canceled"]].map(([label, key]) => <div key={key}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 text-xl font-medium">{counts[key]}</dd></div>)}</dl></div>
      <dl className="flex flex-wrap gap-8">{[["기한 초과", "overdue"], ["오늘 마감", "due_today"], ["7일 이내", "due_week"], ["선행 과제 대기", "blocked"]].map(([label, key]) => <div key={key}><dt className="text-sm text-slate-500">{label}</dt><dd className={`mt-1 text-2xl font-semibold ${key === "overdue" && counts[key] ? "text-red-700" : ""}`}>{counts[key]}</dd></div>)}</dl>
      <div className="grid gap-8 lg:grid-cols-2"><section aria-label="담당자 현황"><h3 className="mb-3 font-semibold">담당자별 미완료 과제</h3><ul className="divide-y border-y">{query.data?.workload.map(row => <li key={row.assignee_id ?? "none"} className="flex flex-wrap justify-between gap-2 py-3 text-sm"><span className="break-all">{row.email ?? (row.assignee_id ? "이전 담당자" : "미지정")}</span><span>{row.open}개 · 기한 초과 {row.overdue}</span></li>)}</ul>{!query.data?.workload.length && <p className="mt-3 text-sm text-slate-500">남은 과제가 없습니다.</p>}{query.data?.workload_has_more && <p className="text-xs">과제가 많은 담당자 100명까지 표시합니다.</p>}</section>
      <section aria-label="임박 과제"><h3 className="mb-3 font-semibold">마감 순서 · 최대 10개</h3><ul className="divide-y border-y">{query.data?.upcoming.map(task => <li key={task.id} className="flex flex-wrap justify-between gap-2 py-3 text-sm"><Link className="break-words text-indigo-700 underline" href={`/dashboard/projects/${projectId}?view=tasks&task=${task.id}`}>{task.title}</Link><time>{task.due_date}</time></li>)}</ul>{!query.data?.upcoming.length && <p className="mt-3 text-sm text-slate-500">기한이 정해진 미완료 과제가 없습니다.</p>}</section></div></>}
  </section>;
}
