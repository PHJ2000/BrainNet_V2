"use client";
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Core, EventObject } from "cytoscape";
import { v4 as uuid } from "uuid";
import { apiClient } from "@/lib/apiClient";
import { measureNodeSize, type NodeMeta } from "./graphModel";
import { createNode, updateNode, type NodeOut } from "./nodeApi";
import type { useGraphData } from "./useGraphData";
import type { useGraphActions } from "./useGraphActions";
import { useSaveOperation } from "./useSaveOperation";

type Draft = { mode: "edit" | "create"; node: NodeMeta; content: string; key: string };
export function useGraphEditing(data: ReturnType<typeof useGraphData>,
  actions: ReturnType<typeof useGraphActions>, cyRef: RefObject<Core | null>, visible: RefObject<Set<string>>,
  readOnly = false) {
  const { nodesRef, projectIdRef, getScope, updateLocalNode, refreshNodes } = data;
  const save = useSaveOperation(getScope);
  const [draft, setDraft] = useState<Draft | null>(null), draftRef = useRef<Draft | null>(null);
  const [open, setOpen] = useState(false), [latest, setLatest] = useState("");
  const [persistenceError, setPersistenceError] = useState("");
  const storageKey = useRef("");
  const readonlyRef = useRef(readOnly);
  useLayoutEffect(() => { readonlyRef.current = readOnly; }, [readOnly]);
  const { data: user } = useQuery({ queryKey: ["me"], queryFn: async ({ signal }) =>
    (await apiClient.get<{id:number}>("/users/me", { signal })).data, retry: false });
  useEffect(() => {
    if (!user) return;
    let active = true;
    const prefix = `brainnet:draft:${user.id}:${projectIdRef.current}:`;
    void Promise.resolve().then(() => {
      if (!active) return;
      try {
        let slot = sessionStorage.getItem(prefix);
        if (!slot) { slot = uuid(); sessionStorage.setItem(prefix, slot); }
        storageKey.current = prefix + slot;
        const raw = localStorage.getItem(storageKey.current);
        if (raw) {
          const restored: Draft = JSON.parse(raw);
          if (["edit", "create"].includes(restored.mode) && typeof restored.content === "string" &&
              restored.content.length <= 8000 && typeof restored.key === "string" && restored.node?.id && Number.isInteger(restored.node.version)) {
            draftRef.current = restored; setDraft(restored);
          }
        }
      } catch { setPersistenceError("초안을 보관할 수 없습니다. 닫기 전에 내용을 복사해 주세요."); }
    });
    return () => { active = false; };
  }, [user, projectIdRef]);
  const persist = (value: Draft | null) => {
    draftRef.current = value; setDraft(value);
    try {
      if (!storageKey.current) throw new Error("Account not ready");
      if (value) localStorage.setItem(storageKey.current, JSON.stringify(value));
      else localStorage.removeItem(storageKey.current);
    } catch { setPersistenceError("초안을 보관할 수 없습니다. 닫기 전에 내용을 복사해 주세요."); }
  };
  const apply = (saved: NodeOut) => {
    const current = nodesRef.current.find(n => n.id === String(saved.id));
    if (current && current.version > saved.version) return current;
    return updateLocalNode(String(saved.id), node => ({ ...node, label: saved.content,
      pos_x: saved.pos_x ?? node.pos_x, pos_y: saved.pos_y ?? node.pos_y,
      version: saved.version, ...measureNodeSize(saved.content) }));
  };
  const start = (node: NodeMeta, mode: Draft["mode"]) => {
    if (readonlyRef.current || !storageKey.current) return;
    if (draftRef.current) { setOpen(true); return; }
    if (save.isBlocked()) return;
    persist({ mode, node, content: mode === "create" || node.label === "?" ? "" : node.label, key: uuid() });
    setLatest(""); setOpen(true);
  };
  const handleTap = (event: EventObject) => {
    const node = nodesRef.current.find(n => n.id === event.target.id());
    if (node && visible.current.has(node.id)) start(node, "edit");
  };
  const submit = async () => {
    const value = draftRef.current;
    if (!value?.content.trim() || readonlyRef.current) return;
    const projectId = projectIdRef.current, scope = getScope();
    await save.run(async () => {
      if (value.mode === "create") {
        await createNode(projectId, { content: value.content, parent_id: Number(value.node.id), depth: value.node.depth + 1,
          pos_x: value.node.pos_x + 180, pos_y: value.node.pos_y + 120 }, value.key, scope.signal);
        if (scope.isCurrent()) await refreshNodes(projectId, true);
      } else {
        const saved = await updateNode(projectId, value.node.id, { content: value.content, expected_version: value.node.version }, scope.signal, value.key);
        if (scope.isCurrent()) {
          const node = apply(saved);
          if (value.node.status === "GHOST" && node) await actions.activateNodeLocal(node, true);
        }
      }
      if (scope.isCurrent()) { persist(null); setOpen(false); setLatest(""); }
    }, value.content);
  };
  const handleDrag = async (event: EventObject) => {
    const id = String(event.target.id()), position = { ...event.target.position() };
    const node = nodesRef.current.find(n => n.id === id);
    if (!node || !visible.current.has(id)) return;
    if (readonlyRef.current || save.isBlocked()) { event.target.position({ x: node.pos_x, y: node.pos_y }); return; }
    const projectId = projectIdRef.current, scope = getScope(), key = uuid();
    const saved = await save.run(async () => {
      const result = await updateNode(projectId, id, { pos_x: position.x, pos_y: position.y, expected_version: node.version }, scope.signal, key);
      if (scope.isCurrent()) apply(result);
    }, `위치: ${Math.round(position.x)}, ${Math.round(position.y)}`);
    if (!saved && scope.isCurrent()) cyRef.current?.$id(id).position({ x: node.pos_x, y: node.pos_y });
  };
  return { readOnly, save, handleTap, handleDrag, draft, open, latest, persistenceError, submit,
    addChild: (parent: NodeMeta) => start(parent, "create"),
    generate: (parent: NodeMeta) => readonlyRef.current ? Promise.resolve(false) : save.run(() => actions.spawnChildren(parent, true), "AI 아이디어 생성"),
    change: (content: string) => { if (draftRef.current && !save.isBlocked()) persist({ ...draftRef.current, content }); },
    close: () => setOpen(false), resume: () => setOpen(true),
    discard: () => { save.discard(); persist(null); setOpen(false); setLatest(""); },
    readLatest: async () => { const nodes = await refreshNodes(projectIdRef.current, true).catch(() => undefined);
      setLatest(nodes?.find(n => n.id === draftRef.current?.node.id)?.label ?? "현재 상태를 불러오지 못했거나 노드가 삭제되었습니다."); } };
}
