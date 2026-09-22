// features/projects/nodeApi.ts
import { apiClient } from "@/lib/apiClient";
import type { NodeMeta } from "./Graph";
import { createRequest } from "./createRequest";
/* ─────────────────────────────
   공통 타입
   ────────────────────────────*/
export interface NodeOut {
  id: number;
  project_id: number;
  author_id: number;
  content: string;
  state: "ACTIVE" | "GHOST" | "ARCHIVED";
  pos_x: number;
  pos_y: number;
  depth: number;
  order_index: number;
  parent_id?: number | null;
  created_at: string;
  updated_at: string;
  tags: number[];
  version: number;
}

export interface NodePayload {
  content?: string;
  pos_x?: number;
  pos_y?: number;
  depth?: number;
  order?: number;
  parent_id?: number | null;
  state?:  string;
}

export type NodeUpdatePayload = Partial<NodePayload> & {
  expected_version: number;
};

/* ────────── GET: 노드 목록 ──────────*/
export async function fetchNodes(
  projectId: number | string,
  tagIds?: (number | string)[],
  signal?: AbortSignal,
): Promise<NodeOut[]> {
  const query =
    tagIds && tagIds.length ? `?tag_ids=${tagIds.join(",")}` : "";
  const { data } = await apiClient.get(
    `/projects/${projectId}/nodes${query}`, { signal }
  );
  return data;
}

/** Cache belongs to one mounted project/account, never a shared global snapshot. */
export async function fetchGraphSnapshot(projectId: number, etag: string | undefined, signal: AbortSignal) {
  const response = await apiClient.get<NodeOut[]>(`/projects/${projectId}/nodes`, {
    signal, headers: { "X-Graph-Cache": "1", ...(etag ? { "If-None-Match": etag } : {}) },
    validateStatus: status => status === 304 || (status >= 200 && status < 300),
  });
  return { unchanged: response.status === 304, nodes: response.data, etag: response.headers.etag as string | undefined };
}

/* ────────── POST: 일반 노드 생성 ──────────*/
export async function createNode(
  projectId: number | string,
  payload: NodePayload,
  idempotencyKey?: string,
  signal?: AbortSignal,
): Promise<NodeOut> {
  const { data } = await createRequest((key) => apiClient.post(
    `/projects/${projectId}/nodes`,
    payload,
    { headers: { "Idempotency-Key": key }, timeout: 45000, signal },
  ), idempotencyKey);
  // 백엔드가 [NodeOut] 배열을 돌려주므로 첫 원소만 반환
  return Array.isArray(data) ? data[0] : data;
}

/* ────────── POST: AI 제안(GHOST) 노드 ──────────*/
export async function createAINodes(
  projectId: number | string,
  aiPrompt: string,
  opts: {
    pos_x?: number;
    pos_y?: number;
    depth?: number;
    order?: number;
    parent_id?: number | string | null;
  } = {},
  idempotencyKey?: string,
  signal?: AbortSignal,
): Promise<NodeOut[]> {
  const payload = { ai_prompt: aiPrompt, ...opts };
  const { data } = await createRequest((key) => apiClient.post(
    `/projects/${projectId}/nodes`,
    payload,
    { headers: { "Idempotency-Key": key }, timeout: 45000, signal },
  ), idempotencyKey);
  return data;
}

/* ────────── PATCH: 노드 수정 ──────────*/
export async function updateNode(
  projectId: number | string,
  nodeId: number | string,
  payload: NodeUpdatePayload,
  signal?: AbortSignal,
  idempotencyKey?: string,
): Promise<NodeOut> {
  const { data } = await createRequest((key) => apiClient.patch(
    `/projects/${projectId}/nodes/${nodeId}`,
    payload, { headers: { "Idempotency-Key": key }, signal }
  ), idempotencyKey);
  return data;
}

/* ────────── DELETE: 노드 삭제 ──────────*/
export async function deleteNode(
  projectId: number | string,
  nodeId: number | string
) {
  await apiClient.delete(`/projects/${projectId}/nodes/${nodeId}`);
}

/* ────────── POST: GHOST → ACTIVE ──────────*/
export async function activateNode(
  projectId: number | string,
  nodeId: number | string,
  signal?: AbortSignal,
): Promise<NodeOut> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/nodes/${nodeId}/activate`, undefined, { signal }
  );
  return data;
}

/* ────────── POST: ACTIVE → GHOST ──────────*/
export async function deactivateNode(
  projectId: number | string,
  nodeId: number | string
): Promise<NodeOut> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/nodes/${nodeId}/deactivate`
  );
  return data;
}

export function findChildrenIds(nodes: NodeMeta[], parentId: string): string[] {
  let result: string[] = [];
  for (const n of nodes) {
    if (n.parentId === parentId) {
      result.push(n.id);
      // 자식의 자식도 포함 (재귀)
      result = result.concat(findChildrenIds(nodes, n.id));
    }
  }
  return result;
}
