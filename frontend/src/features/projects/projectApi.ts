// features/projects/projectApi.ts
import { apiClient } from "@/lib/apiClient";
import { Project } from "@/types/api";

export const fetchProjects = async (): Promise<Project[]> => {
  const res = await apiClient.get("/projects");
  return res.data;
};

export const createProject = async ({
  name,
  description,
}: {
  name: string;
  description?: string;
}): Promise<Project> => {
  const res = await apiClient.post("/projects", { name, description });
  return res.data;
};

export async function updateProject(id: string, body: { name: string; description: string }): Promise<Project> {
  return (await apiClient.patch(`/projects/${id}`, body)).data;
}

export async function deleteProject(id: string): Promise<void> {
  await apiClient.delete(`/projects/${id}`);
}

export async function inviteProject(id: string, email: string, role: "EDITOR" | "VIEWER" = "EDITOR"): Promise<{ invite_token: string }> {
  return (await apiClient.post(`/projects/${id}/invite`, undefined, { params: { email, role } })).data;
}

export async function joinProject(token: string): Promise<{ project_id: number }> {
  return (await apiClient.post("/projects/join", { token })).data;
}
