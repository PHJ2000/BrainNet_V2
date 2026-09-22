import axios from "axios";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";

export const button = "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-indigo-600";
export const primary = `${button} !border-indigo-700 !bg-indigo-700 !text-white hover:!bg-indigo-800`;
export const field = "mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-2 focus:outline-indigo-600";
export const statuses = { TODO: "할 일", DOING: "진행 중", DONE: "완료", CANCELED: "취소" };
export const priorities = { LOW: "낮음", MEDIUM: "보통", HIGH: "높음" };
export type Task = { id: string; title: string; body: string; status: keyof typeof statuses; priority: keyof typeof priorities; assignee_id: number | null; due_date: string | null; node_id: number | null; version: number; created_at: string };
export type Discussion = { id: string; body: string; author_id: number | null; node_id: number | null; resolved: boolean; version: number; created_at: string };
export type Knowledge = { id: number; project_id: number; project_name: string; content: string; bookmarked: boolean; version: number; state: string };
export type Proposal = { id: string; mode: "EXPAND" | "SUMMARY" | "ACTION"; instruction: string; sources: {id: number; version: number; content: string}[]; status: string; output: string | null; error_code: string | null; task_id: string | null; created_at: string };
export type Member = { user_id: number; email: string; role: string };
export type Page<T> = { items: T[]; next_cursor: string | number | null };

export function useWorkspaceList<T>(projectId: number, resource: string, filters: Record<string, string> = {}) {
  return useInfiniteQuery({ queryKey: ["workspace", projectId, resource, filters], initialPageParam: null as string | number | null,
    queryFn: async ({ signal, pageParam }) => (await apiClient.get<Page<T>>(`/projects/${projectId}/${resource}`, { signal, params: { ...filters, ...(pageParam ? { before: pageParam } : {}) } })).data,
    refetchInterval: resource === "proposals" ? 3000 : false,
    getNextPageParam: page => page.next_cursor ?? undefined, retry: false, refetchOnWindowFocus: true });
}

export function useMembers(projectId: number) {
  return useQuery({ queryKey: ["workspace", projectId, "members"], retry: false,
    queryFn: async ({ signal }) => (await apiClient.get<Member[]>(`/projects/${projectId}/members`, { signal })).data });
}

export function workspaceError(error: unknown): string {
  const code = axios.isAxiosError(error) ? error.response?.data?.code : "";
  const messages: Record<string, string> = {
    TASK_BLOCKED: "선행 과제를 먼저 완료해 주세요.",
    TASK_DEPENDENTS_DONE: "이 과제를 선행 조건으로 삼는 완료 과제를 먼저 다시 열어 주세요.",
    DEPENDENCY_CYCLE: "서로를 선행 조건으로 삼는 순환 관계는 만들 수 없습니다.",
    INVALID_MENTION: "현재 프로젝트에 참여 중인 멤버만 알림 대상으로 선택할 수 있습니다.",
    ASSET_NAME_USED: "이미 사용한 이름입니다. 다른 이름을 입력해 주세요.",
    ASSET_LIMIT: "저장 검색과 템플릿은 각각 30개까지 보관할 수 있습니다.",
    TEMPLATE_TOO_LARGE: "템플릿은 1 MiB 이하로 저장할 수 있습니다. 큰 프로젝트는 JSON 백업을 이용해 주세요.",
    VERSION_CONFLICT: "다른 사람이 수정했습니다. 입력 내용을 복사해 둔 뒤 최신 내용을 불러와 다시 편집해 주세요.",
    AI_SOURCE_CHANGED: "원본 노드가 변경되거나 삭제되었습니다. 현재 내용으로 새 제안을 요청해 주세요.",
    AI_PROJECT_LIMIT: "프로젝트의 24시간 요청 한도 또는 대기열 한도에 도달했습니다. 사용량 설정을 확인해 주세요.",
    AI_SOURCE_TOO_LARGE: "노드당 4,000자, 전체 16,000자 이하로 선택해 주세요.",
    REQUEST_ID_REUSED: "이미 처리된 요청과 입력이 다릅니다. 목록을 새로고침해 결과를 확인해 주세요.",
    INVALID_ASSIGNEE: "담당자는 현재 프로젝트의 소유자 또는 편집자여야 합니다.",
  };
  if (messages[code]) return messages[code];
  const status = axios.isAxiosError(error) ? error.response?.status : undefined;
  if (status === 403 || status === 404) return "항목이 없거나 접근 권한이 변경되었습니다. 프로젝트를 다시 열어 주세요.";
  if (status === 422) return "입력 길이와 연결한 노드, 담당자를 확인해 주세요.";
  return "저장 결과를 확인하지 못했습니다. 같은 요청으로 다시 시도하거나 목록을 새로고침해 주세요.";
}

export function TaskPayload(task: Task) {
  const { title, body, status, priority, assignee_id, due_date, node_id } = task;
  return { title, body, status, priority, assignee_id, due_date, node_id };
}
