// types/api.d.ts

export interface User {
  id: string;
  email: string;
  name?: string;
  created_at: string;
  updated_at?: string;
}

export interface Project {
  my_role?: "OWNER" | "EDITOR" | "VIEWER";
  ai_enabled?: boolean;
  id: string;
  name: string;
  description?: string;
  owner_id: string;
  created_at: string;
  updated_at: string;
  member_count?: number;
  node_count?: number;
  tag_count?: number;
}

export type NodeStatus = "ACTIVE" | "GHOST";

export interface Node {
  id: string;
  content: string;
  status: NodeStatus;
  x: number;
  y: number;
  depth: number;
  order: number;
  tags: string[];
}

export interface Tag {
  id: string;
  name: string;
  description?: string;
  color?: string;
  node_count?: number;
  summary?: string;
}

export interface ProjectHistoryEntry {
  id: number;
  project_id: string;
  tag_id: string;
  summary: string;
  decided_at: string;
  decided_by: string;
}
