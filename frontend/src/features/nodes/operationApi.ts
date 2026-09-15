import axios from "axios";
import { apiClient } from "@/lib/apiClient";
import { createRequest } from "./createRequest";

export interface Operation {
  id: string; node_id: number; kind: "create" | "update" | "delete" | "undo";
  actor_id: number | null; created_at: string; expires_at: string;
  expired: boolean; undone_by: string | null; can_undo: boolean; node_count: number;
}
export interface OperationPreview extends Operation {
  preview_hash: string;
  before: { nodes?: { id: number; content: string; pos_x: number | null; pos_y: number | null }[] };
  after: { nodes?: { id: number; content: string; pos_x: number | null; pos_y: number | null }[] };
}
export interface DeletePreview {
  nodes: { id: number; content: string }[]; node_count: number;
  expected_version: number; scope_hash: string;
}
export const listOperations = (pid: number, before?: string) =>
  apiClient.get<{ items: Operation[]; next_cursor: string | null }>(`/projects/${pid}/operations`,
    { params: { before }, timeout: 30000 }).then(r => r.data);
export const previewOperation = (pid: number, id: string) =>
  apiClient.get<OperationPreview>(`/projects/${pid}/operations/${id}/preview`, { timeout: 30000 }).then(r => r.data);
export const undoOperation = (pid: number, preview: OperationPreview, key: string) =>
  createRequest(k => apiClient.post(`/projects/${pid}/operations/${preview.id}/undo`,
    { preview_hash: preview.preview_hash }, { headers: { "Idempotency-Key": k }, timeout: 30000 }), key);
export const previewDelete = (pid: number, id: string) =>
  apiClient.get<DeletePreview>(`/projects/${pid}/nodes/${id}/delete-preview`, { timeout: 30000 }).then(r => r.data);
export const confirmDelete = (pid: number, id: string, preview: DeletePreview, key: string) =>
  createRequest(k => apiClient.delete(`/projects/${pid}/nodes/${id}`, {
    params: { expected_version: preview.expected_version, scope_hash: preview.scope_hash },
    headers: { "Idempotency-Key": k },
    timeout: 30000,
  }), key);

export function operationError(error: unknown): string {
  if (!axios.isAxiosError(error)) return "작업을 완료하지 못했어요. 다시 시도해 주세요.";
  const code = error.response?.data?.code;
  if (code === "OPERATION_EXPIRED") return "30일 보존 기간이 지나 복구할 수 없어요.";
  if (code === "OPERATION_FORBIDDEN") return "자신의 작업만 되돌릴 수 있어요.";
  if (code === "OPERATION_ALREADY_UNDONE") return "이미 되돌린 작업이에요. 기록을 다시 불러와 주세요.";
  if (error.response?.status === 409 || error.response?.status === 404)
    return "대상이나 연결된 데이터가 바뀌었어요. 최신 상태를 확인하고 미리보기를 다시 열어 주세요.";
  if (!error.response) return "서버 응답을 확인하지 못했어요. 같은 요청으로 다시 시도할 수 있어요.";
  return "작업을 완료하지 못했어요. 입력을 유지했으니 연결과 권한을 확인해 주세요.";
}
