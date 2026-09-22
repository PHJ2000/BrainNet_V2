// features/projects/tagApi.ts
import { apiClient } from "@/lib/apiClient";

export interface TagResponse {
  id: number;
  name: string;
  description?: string;
  color?: string;
  node_count: number;
  summary?: string;
}

export interface TagPayload {
  name?: string;
  color?: string;
}

export const listTags = (pid: string | number, signal?: AbortSignal): Promise<TagResponse[]> =>
  apiClient.get<TagResponse[]>(`/projects/${pid}/tags`, { signal }).then((response) => response.data);
export const createTag = (
  pid: string | number,
  body: TagPayload,
): Promise<TagResponse> =>
  apiClient
    .post<TagResponse>(`/projects/${pid}/tags`, body)
    .then((response) => response.data);
export const updateTag = (
  pid: string | number,
  tid: string | number,
  body: TagPayload,
): Promise<TagResponse> =>
  apiClient
    .patch<TagResponse>(`/projects/${pid}/tags/${tid}`, body)
    .then((response) => response.data);
export const deleteTag  = (pid: string | number, tid: string | number) => apiClient.delete(`/projects/${pid}/tags/${tid}`);
export const attachTag  = (pid: string | number, tid: string | number, nid: string | number) => apiClient.post(`/projects/${pid}/tags/${tid}/nodes/${nid}`).then(r=>r.data);
export const detachTag  = (pid: string | number, tid: string | number, nid: string | number) => apiClient.delete(`/projects/${pid}/tags/${tid}/nodes/${nid}`).then(r=>r.data);
