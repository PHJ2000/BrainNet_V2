"use client";
import { useRef, type RefObject } from "react";
import type { useGraphData } from "./useGraphData";
import { useSaveOperation } from "./useSaveOperation";
import type { NodeMeta } from "./graphModel";
import { childCreationPlan, runChildCreationPlan, type ChildCreationPlan } from "./childCreationPlan";
import { createAINodes as apiCreateAINodes, createNode, activateNode as apiActivateNode } from "./nodeApi";
import { attachTag, detachTag, createTag, listTags } from "@/features/projects/tagApi";

/** User commands retain their retry state independently of canvas rendering. */
export function useGraphActions(data: ReturnType<typeof useGraphData>, ctxNodeId: string | null, visibleRef: RefObject<Set<string>>) {
  const { nodesRef, projectIdRef, getScope, refreshNodes, updateLocalNode, resyncNodes } = data;
  /* ----- util ----- */
  const radius = 280;
  const polarToXY = (cx: number, cy: number, r: number, rad: number) => ({
    x: cx + r * Math.cos(rad),
    y: cy + r * Math.sin(rad),
  });

  const tagSave = useSaveOperation(getScope);
  const handleAddTag = async (tagId: string) => {
    if (!ctxNodeId || !visibleRef.current.has(ctxNodeId) || tagSave.isBlocked()) return;
    const projectId = projectIdRef.current, nodeId = ctxNodeId, scope = getScope();
    const name = tagId === "__new__" ? window.prompt("새 태그 이름")?.trim() : undefined;
    if (tagId === "__new__" && !name) return;
    let realId = tagId;
    await tagSave.run(async () => {
      if (realId === "__new__") {
        const existing = (await listTags(projectId, scope.signal)).find(t => t.name === name);
        realId = String(existing?.id ?? (await createTag(projectId, { name: name! })).id);
      }
      if (!scope.isCurrent()) return;
      const snapshot = await refreshNodes(projectId, true);
      if (!snapshot?.find(n => n.id === nodeId)?.tags?.includes(realId)) await attachTag(projectId, realId, nodeId);
      if (scope.isCurrent()) await refreshNodes(projectId, true);
    }, name ? `태그: ${name}` : "태그 연결");
  };
  const handleRemoveTag = async (tagId: string) => {
    if (!ctxNodeId || !visibleRef.current.has(ctxNodeId)) return;
    const projectId = projectIdRef.current, nodeId = ctxNodeId, scope = getScope();
    await tagSave.run(async () => {
      const snapshot = await refreshNodes(projectId, true);
      if (scope.isCurrent() && snapshot?.find(n => n.id === nodeId)?.tags?.includes(tagId)) await detachTag(projectId, tagId, nodeId);
      if (scope.isCurrent()) await refreshNodes(projectId, true);
    }, "태그 연결 해제");
  };

  /* ----- AI·빈 노드 생성 로직 ----- */
  const spawning = useRef(new Set<string>());
  const spawnPlans = useRef(new Map<string, ChildCreationPlan>());
  const spawnChildren = async (parent: NodeMeta, propagate = false) => {
    if (parent.generated) return;
    const targetProjectId = projectIdRef.current;
    const scope = getScope();
    if (!scope.isCurrent()) return;
    const operation = `${targetProjectId}:${parent.id}`;
    if (spawning.current.has(operation)) return;
    spawning.current.add(operation);
    try {
      let plan = spawnPlans.current.get(operation);
      if (!plan) {
        const isRoot = !parent.parentId;
        const grandparent = nodesRef.current.find((node) => node.id === parent.parentId);
        const direction = grandparent
          ? Math.atan2(parent.pos_y - grandparent.pos_y, parent.pos_x - grandparent.pos_x) : 0;
        const angles = isRoot
          ? Array.from({ length: 3 }, (_, index) => -Math.PI / 2 + index * 2 * Math.PI / 3)
          : [direction - Math.PI / 6, direction + Math.PI / 6];
        plan = childCreationPlan(parent.label, isRoot ? 2 : 1, angles.map((angle, index) => {
          const { x, y } = polarToXY(parent.pos_x, parent.pos_y, radius, angle);
          return {
            content: "?", parent_id: Number(parent.id), pos_x: x, pos_y: y,
            depth: parent.depth + 1, order: index, state: "GHOST",
          };
        }));
        spawnPlans.current.set(operation, plan);
      }
      const complete = await runChildCreationPlan(plan, {
        ai: (prompt, payload, key) => apiCreateAINodes(targetProjectId, prompt, payload, key, scope.signal),
        regular: (payload, key) => createNode(targetProjectId, payload, key, scope.signal),
      }, scope.isCurrent, false);
      if (!complete) return;
      await refreshNodes(targetProjectId, true);
      if (!scope.isCurrent()) return;
      updateLocalNode(parent.id, (node) => ({ ...node, frozen: true, generated: true }));
      spawnPlans.current.delete(operation);
    } catch (error) {
      if (!scope.isCurrent()) return;
      console.error(error);
      try {
        await refreshNodes(targetProjectId);
      } catch (refreshError) {
        console.error(refreshError);
      }
      if (propagate) throw error;
    } finally {
      spawning.current.delete(operation);
    }
  };

  /* ----- 노드 활성화 ----- */
  const activateNodeLocal = async (meta: NodeMeta, propagate = false): Promise<NodeMeta | undefined> => {
    const targetProjectId = projectIdRef.current;
    const scope = getScope();
    if (!scope.isCurrent()) return;
    try {
      await apiActivateNode(targetProjectId, Number(meta.id), scope.signal);
      const refreshed = await refreshNodes(targetProjectId, true);
      return refreshed?.find((node) => node.id === meta.id);
    } catch (e) {
      console.error(e);
      if (!scope.isCurrent()) return undefined;
      await resyncNodes();
      if (propagate) throw e;
      return undefined;
    }
  };

  return { tagSave, handleAddTag, handleRemoveTag, spawnChildren, activateNodeLocal };
}
