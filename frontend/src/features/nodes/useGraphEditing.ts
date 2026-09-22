"use client";
import type { RefObject } from "react";
import type { Core, EventObject } from "cytoscape";
import { v4 as uuid } from "uuid";
import { measureNodeSize, type NodeMeta } from "./graphModel";
import { createNode, updateNode, type NodeOut } from "./nodeApi";
import type { useGraphData } from "./useGraphData";
import type { useGraphActions } from "./useGraphActions";
import { useSaveOperation } from "./useSaveOperation";

export function useGraphEditing(data: ReturnType<typeof useGraphData>,
  actions: ReturnType<typeof useGraphActions>, cyRef: RefObject<Core | null>, visible: RefObject<Set<string>>) {
  const { nodesRef, projectIdRef, getScope, updateLocalNode, refreshNodes } = data;
  const save = useSaveOperation(getScope);
  const apply = (saved: NodeOut) => {
    const current = nodesRef.current.find(n => n.id === String(saved.id));
    if (current && current.version > saved.version) return current;
    return updateLocalNode(String(saved.id), node => ({ ...node, label: saved.content,
      pos_x: saved.pos_x ?? node.pos_x, pos_y: saved.pos_y ?? node.pos_y,
      version: saved.version, ...measureNodeSize(saved.content) }));
  };
  const handleTap = async (event: EventObject) => {
    if (save.isBlocked()) return;
    const node = nodesRef.current.find(n => n.id === event.target.id());
    if (!node || !visible.current.has(node.id)) return;
    const projectId = projectIdRef.current, scope = getScope(), key = uuid();
    if (node.status === "GHOST" && node.label !== "?") {
      await save.run(async () => { await actions.activateNodeLocal(node, true); }, "노드 활성화");
      return;
    }
    const input = window.prompt(node.status === "GHOST" ? "노드 내용을 입력하세요" : "노드 내용을 수정하세요", node.label);
    if (!input?.trim() || input === node.label) return;
    await save.run(async () => {
      const saved = await updateNode(projectId, Number(node.id), { content: input, expected_version: node.version }, scope.signal, key);
      if (!scope.isCurrent()) return;
      let updated = apply(saved) ?? node;
      if (node.status === "GHOST") updated = await actions.activateNodeLocal(updated, true) ?? updated;
      if (!updated.generated) await actions.spawnChildren(updated, true);
    }, input);
  };
  const handleDrag = async (event: EventObject) => {
    const id = String(event.target.id()), position = { ...event.target.position() };
    const node = nodesRef.current.find(n => n.id === id);
    if (!node || !visible.current.has(id)) return;
    if (save.isBlocked()) { event.target.position({ x: node.pos_x, y: node.pos_y }); return; }
    const projectId = projectIdRef.current, scope = getScope(), key = uuid();
    const saved = await save.run(async () => {
      const result = await updateNode(projectId, id, { pos_x: position.x, pos_y: position.y, expected_version: node.version }, scope.signal, key);
      if (scope.isCurrent()) apply(result);
    }, `위치: ${Math.round(position.x)}, ${Math.round(position.y)}`);
    if (!saved && scope.isCurrent()) cyRef.current?.$id(id).position({ x: node.pos_x, y: node.pos_y });
  };
  const addChild = async (parent: NodeMeta) => {
    if (save.isBlocked()) return;
    const content = window.prompt("새 자식 노드의 내용을 입력하세요");
    if (!content?.trim()) return;
    const projectId = projectIdRef.current, scope = getScope(), key = uuid();
    await save.run(async () => {
      await createNode(projectId, { content, parent_id: Number(parent.id), depth: parent.depth + 1,
        pos_x: parent.pos_x + 180, pos_y: parent.pos_y + 120 }, key, scope.signal);
      if (scope.isCurrent()) await refreshNodes(projectId, true);
    }, content);
  };
  return { save, handleTap, handleDrag, addChild };
}
