"use client";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { listTags } from "@/features/projects/tagApi";
import { fetchNodes } from "./nodeApi";
import { NodeMeta, Tag, toNodeMeta } from "./graphModel";
import { useNodeEvents } from "./useNodeEvents";

/** Owns server snapshots and local edits independently of the canvas renderer. */
export function useGraphData(projectId: number) {
  const [nodes, setNodes] = useState<NodeMeta[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [loaded, setLoaded] = useState(false);
  const nodesRef = useRef(nodes);
  const projectIdRef = useRef(projectId);
  const refreshSequence = useRef(0);
  const alive = useRef(true);
  const controller = useRef(new AbortController());
  useLayoutEffect(() => {
    controller.current = new AbortController();
    projectIdRef.current = projectId;
    alive.current = true;
    refreshSequence.current++;
    return () => { alive.current = false; controller.current.abort(); };
  }, [projectId]);

  const getScope = useCallback(() => {
    const activeController = controller.current;
    const id = projectIdRef.current;
    return { signal: activeController.signal, isCurrent: () => alive.current &&
      id === projectIdRef.current && activeController === controller.current && !activeController.signal.aborted };
  }, []);

  const refreshNodes = useCallback(async (targetProjectId = projectIdRef.current) => {
    const scope = getScope();
    if (!scope.isCurrent() || targetProjectId !== projectIdRef.current) return;
    const sequence = ++refreshSequence.current;
    const [list, tagList] = await Promise.all([fetchNodes(targetProjectId), listTags(targetProjectId)]);
    if (!scope.isCurrent() || targetProjectId !== projectIdRef.current || sequence !== refreshSequence.current) return;
    const previous = new Map(nodesRef.current.map(node => [node.id, node]));
    const next = list.map(node => toNodeMeta(node, previous.get(String(node.id))));
    nodesRef.current = next;
    setNodes(next);
    setTags(tagList.map(tag => ({ ...tag, id: String(tag.id) })));
    setLoaded(true);
    return next;
  }, [getScope]);
  const accessError = useNodeEvents(projectId, refreshNodes);
  useEffect(() => { void refreshNodes(projectId).catch(console.error); }, [projectId, refreshNodes]);

  const updateNodesAndCy = (updater: (current: NodeMeta[]) => NodeMeta[]) => {
    const next = updater(nodesRef.current);
    nodesRef.current = next;
    setNodes(next);
  };
  const updateLocalNode = (id: string, updater: (node: NodeMeta) => NodeMeta) => {
    const next = nodesRef.current.map(node => node.id === id ? updater(node) : node);
    nodesRef.current = next;
    setNodes(next);
    return next.find(node => node.id === id);
  };
  const resyncNodes = async (fallback?: () => void) => {
    try { await refreshNodes(projectIdRef.current); }
    catch (error) { console.error("노드 서버 상태 재동기화 실패", error); if (alive.current) fallback?.(); }
  };
  return { nodes, nodesRef, tags, setTags, loaded, accessError, projectIdRef, getScope, refreshNodes,
    updateNodesAndCy, updateLocalNode, resyncNodes };
}
