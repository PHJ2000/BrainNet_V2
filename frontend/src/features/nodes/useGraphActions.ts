"use client";
import { useRef, type RefObject } from "react";
import type { useGraphData } from "./useGraphData";
import type { NodeMeta } from "./graphModel";
import { childCreationPlan, runChildCreationPlan, type ChildCreationPlan } from "./childCreationPlan";
import { createAINodes as apiCreateAINodes, createNode, activateNode as apiActivateNode, findChildrenIds } from "./nodeApi";
import { attachTag, detachTag, createTag } from "@/features/projects/tagApi";

/** User commands retain their retry state independently of canvas rendering. */
export function useGraphActions(data: ReturnType<typeof useGraphData>, ctxNodeId: string | null, visibleRef: RefObject<Set<string>>) {
  const { nodesRef, projectIdRef, getScope, setTags, refreshNodes, updateNodesAndCy, updateLocalNode, resyncNodes } = data;
  /* ----- util ----- */
  const radius = 280;
  const polarToXY = (cx: number, cy: number, r: number, rad: number) => ({
    x: cx + r * Math.cos(rad),
    y: cy + r * Math.sin(rad),
  });

  /* ----- 태그 attach / detach ----- */
  const handleAddTag = async (tagId: string) => {
    if (!ctxNodeId || !visibleRef.current.has(ctxNodeId)) return;
    const targetProjectId = projectIdRef.current;
    const scope = getScope();
    if (!scope.isCurrent()) return;
    const targetNodeId = ctxNodeId;
    const allNodeIds = [
      targetNodeId,
      ...findChildrenIds(nodesRef.current, targetNodeId),
    ];
    let realId = tagId;

    if (tagId === "__new__") {
      const name = window.prompt("새 태그 이름");
      if (!name) return;
      try {
        const t = await createTag(targetProjectId, { name });
        if (!scope.isCurrent()) return;
        const newTag = { ...t, id: String(t.id) };
        setTags((ts) => [...ts, newTag]);
        realId = newTag.id;
      } catch (e) {
        if (!scope.isCurrent()) return;
        console.error(e);
        return;
      }
    }

    try {
      // 모든 노드에 태그를 attach
      await attachTag(targetProjectId, realId, targetNodeId);
      if (!scope.isCurrent()) return;
      updateNodesAndCy((ns) =>
        ns.map((n) =>
          allNodeIds.includes(n.id)
            ? { ...n, tags: [...(n.tags ?? []), realId] }
            : n
        )
      );
    } catch (e) {
      if (!scope.isCurrent()) return;
      console.error(e);
    }
  };

  const handleRemoveTag = async (tagId: string) => {
    if (!ctxNodeId || !visibleRef.current.has(ctxNodeId)) return;
    const targetProjectId = projectIdRef.current;
    const scope = getScope();
    if (!scope.isCurrent()) return;
    const targetNodeId = ctxNodeId;
    const allNodeIds = [
      targetNodeId,
      ...findChildrenIds(nodesRef.current, targetNodeId),
    ];

    try {
      await detachTag(targetProjectId, tagId, targetNodeId);
      if (!scope.isCurrent()) return;
      updateNodesAndCy((ns) =>
        ns.map((n) =>
          allNodeIds.includes(n.id)
            ? { ...n, tags: (n.tags ?? []).filter((t) => t !== tagId) }
            : n
        )
      );
    } catch (e) {
      if (!scope.isCurrent()) return;
      console.error(e);
    }
  };

  /* ----- AI·빈 노드 생성 로직 ----- */
  const spawning = useRef(new Set<string>());
  const spawnPlans = useRef(new Map<string, ChildCreationPlan>());
  const spawnChildren = async (parent: NodeMeta) => {
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
      }, scope.isCurrent);
      if (!complete) return;
      await refreshNodes(targetProjectId);
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
    } finally {
      spawning.current.delete(operation);
    }
  };

  /* ----- 노드 활성화 ----- */
  const activateNodeLocal = async (meta: NodeMeta): Promise<NodeMeta | undefined> => {
    const targetProjectId = projectIdRef.current;
    const scope = getScope();
    if (!scope.isCurrent()) return;
    try {
      await apiActivateNode(targetProjectId, Number(meta.id), scope.signal);
      const refreshed = await refreshNodes(targetProjectId);
      return refreshed?.find((node) => node.id === meta.id);
    } catch (e) {
      console.error(e);
      if (!scope.isCurrent()) return undefined;
      await resyncNodes();
      return undefined;
    }
  };

  return { handleAddTag, handleRemoveTag, spawnChildren, activateNodeLocal };
}
