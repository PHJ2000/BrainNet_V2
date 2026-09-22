"use client";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { listTags } from "@/features/projects/tagApi";
import { fetchNodes } from "./nodeApi";
import { NodeMeta, Tag, toNodeMeta } from "./graphModel";
import { useNodeEvents } from "./useNodeEvents";
import { projectError } from "@/features/projects/projectError";

/** Owns server snapshots and local edits independently of the canvas renderer. */
export function useGraphData(projectId: number) {
  const [nodes, setNodes] = useState<NodeMeta[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const nodesRef = useRef(nodes);
  const projectIdRef = useRef(projectId);
  const refreshSequence = useRef(0);
  const alive = useRef(true);
  const controller = useRef(new AbortController());
  const inflight = useRef<{ projectId: number; promise: Promise<NodeMeta[] | undefined> } | null>(null);
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

  const refreshNodes = useCallback(function refreshSnapshot(targetProjectId = projectIdRef.current, afterWrite = false): Promise<NodeMeta[] | undefined> {
    const scope = getScope();
    if (!scope.isCurrent() || targetProjectId !== projectIdRef.current) return Promise.resolve(undefined);
    if (inflight.current?.projectId === targetProjectId) return afterWrite
      ? inflight.current.promise.catch(() => undefined).then(() => refreshSnapshot(targetProjectId)) : inflight.current.promise;
    const sequence = ++refreshSequence.current;
    const request = async () => {
      setLoading(true);
      try {
        const [list, tagList] = await Promise.all([fetchNodes(targetProjectId, undefined, scope.signal), listTags(targetProjectId, scope.signal)]);
        if (!scope.isCurrent() || targetProjectId !== projectIdRef.current || sequence !== refreshSequence.current) return;
        const previous = new Map(nodesRef.current.map(node => [node.id, node]));
        const next = list.map(node => toNodeMeta(node, previous.get(String(node.id))));
        if (next.length !== nodesRef.current.length || next.some((node, index) => node !== nodesRef.current[index])) {
          nodesRef.current = next;
          setNodes(next);
        }
        const nextTags = tagList.map(tag => ({ ...tag, id: String(tag.id) }));
        setTags(previousTags => JSON.stringify(previousTags) === JSON.stringify(nextTags) ? previousTags : nextTags);
        setLoaded(true);
        setLoadError(null);
        return next;
      } catch (error) {
        if (scope.isCurrent()) setLoadError(projectError(error));
        throw error;
      } finally {
        if (scope.isCurrent()) setLoading(false);
        if (inflight.current?.promise === promise) inflight.current = null;
      }
    };
    const promise = request();
    inflight.current = { projectId: targetProjectId, promise };
    return promise;
  }, [getScope]);
  const { accessError, connection } = useNodeEvents(projectId, refreshNodes);
  useEffect(() => {
    // The socket resync can start this load sooner; overlap shares the same request.
    const initialSequence = refreshSequence.current;
    const initial = setTimeout(() => {
      if (initialSequence === refreshSequence.current) void refreshNodes(projectId).catch(() => undefined);
    }, 150);
    return () => clearTimeout(initial);
  }, [projectId, refreshNodes]);

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
  return { nodes, nodesRef, tags, setTags, loaded, accessError, connection, loadError, loading, projectIdRef, getScope, refreshNodes,
    updateNodesAndCy, updateLocalNode, resyncNodes };
}
