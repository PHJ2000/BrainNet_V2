"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, memo } from "react";
import cytoscape, { Core, ElementDefinition } from "cytoscape";
import { childCreationPlan, runChildCreationPlan, type ChildCreationPlan } from "./childCreationPlan";
import { useNodeEvents } from "./useNodeEvents";
import OperationPanel from "./OperationPanel";
import GraphExplorer from "./GraphExplorer";
import { useGraphView } from "./useGraphView";
import ProjectFiles from "@/features/projects/ProjectFiles";
import {
  createAINodes as apiCreateAINodes,
  NodeOut,
  createNode,        // ✅ 추가
  activateNode as apiActivateNode,
  updateNode,        // ✅ 추가
  fetchNodes,
  findChildrenIds,
} from "./nodeApi";  // ← 변경
import {
  listTags,
  attachTag,
  detachTag,
  createTag,
} from "@/features/projects/tagApi";
import {
  Menu,
  Item,
  Submenu,
  useContextMenu,
} from "react-contexify";
import "react-contexify/ReactContexify.css";

/* ───────────── 타입 ───────────── */
export interface Tag {
  id: string;
  name: string;
  description?: string;
  color?: string;
  node_count: number;
  summary?: string;
}

export type NodeMeta = {
  id: string;
  label: string;
  pos_x: number;
  pos_y: number;
  parentId?: string;
  depth: number;
  order: number;
  opacity?: number;
  frozen?: boolean;
  status?: "ACTIVE" | "GHOST" | "ARCHIVED";
  generated?: boolean;
  tags?: string[];
  version: number;
  // 자동 크기 조절용
  width?: number;   // 👈 추가!
  height?: number;  // 👈 추가!
};

export interface GraphProps {
  projectId: number;
}

/* ──────────── Context-menu 컴포넌트 ─────────── */
const NODE_MENU_ID = "node-ctx";

interface CtxProps {
  tags: Tag[];
  nodeTags: string[];
  onAdd: (tid: string) => void;
  onRemove: (tid: string) => void;
  onDelete: () => void;
  onCreate: () => void;
  onCollapse: () => void;
}

const NodeContextMenu = memo(function NodeContextMenu({
  tags,
  nodeTags,
  onAdd,
  onRemove,
  onDelete,
  onCreate,
  onCollapse,
}: CtxProps) {
  return (
    <Menu id={NODE_MENU_ID} animation="fade">
      <Item onClick={onCreate}>자식 노드 추가…</Item>
      <Item onClick={onCollapse}>가지 접기 / 펼치기</Item>
      <Item onClick={onDelete}>가지 삭제…</Item>
      <Submenu label="태그 달기…">
        {tags.map((t) => (
          <Item
            key={t.id}
            disabled={nodeTags.includes(t.id)}
            onClick={() => onAdd(t.id)}
          >
            {t.name}
          </Item>
        ))}
        <Item onClick={() => onAdd("__new__")}>+ 새 태그</Item>
      </Submenu>

      {nodeTags.length > 0 && (
        <Submenu label="태그 떼기…">
          {nodeTags.map((tid) => {
            const tg = tags.find((t) => t.id === tid);
            return (
              <Item key={tid} onClick={() => onRemove(tid)}>
                {tg?.name ?? tid}
              </Item>
            );
          })}
        </Submenu>
      )}
    </Menu>
  );
});

function useNodeMenu() {
  const { show } = useContextMenu({ id: NODE_MENU_ID });
  return show;
}
function measureNodeSize(label: string, maxWidth = 220, font = "bold 18px Arial") {
  // 텍스트 줄수와 최대 가로길이에 따라 width, height 산출
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  ctx.font = font;

  // 줄 단위로 나누기 (text-wrap용)
  const words = label.split(' ');
  const lines: string[] = [];
  let curLine = '';

  for (const word of words) {
    const testLine = curLine ? curLine + ' ' + word : word;
    if (ctx.measureText(testLine).width > maxWidth && curLine) {
      lines.push(curLine);
      curLine = word;
    } else {
      curLine = testLine;
    }
  }
  if (curLine) lines.push(curLine);

  const widest = Math.max(...lines.map(l => ctx.measureText(l).width), 70);
  const width = Math.min(Math.max(widest + 40, 110), 350); // min/max clamp
  const height = lines.length * 26 + 30; // 한 줄 26px, +패딩

  return { width, height };
}

function toNodeMeta(n: NodeOut, previous?: NodeMeta): NodeMeta {
  const { width, height } = measureNodeSize(n.content ?? "");
  return {
    id: String(n.id),
    label: n.content,
    pos_x: n.pos_x ?? 400 + Math.min(n.depth, 5) * 120,
    pos_y: n.pos_y ?? 300 + Math.min(n.order_index, 8) * 80,
    parentId: n.parent_id ? String(n.parent_id) : undefined,
    depth: n.depth,
    order: n.order_index,
    status: n.state,
    opacity: n.state === "GHOST" ? 0.3 : 1,
    frozen: n.state === "ACTIVE" ? true : previous?.frozen ?? true,
    generated: previous?.generated,
    version: n.version,
    width,
    height,
    tags: (n.tags ?? []).map(String),
  };
}

/* ──────────── 그래프 컴포넌트 ─────────── */
export default function Graph({ projectId }: GraphProps) {
  const cyRef = useRef<HTMLDivElement>(null);
  const cyInstance = useRef<Core | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tagPopoverOpen, setTagPopoverOpen] = useState(false); // 태그 팝오버/모달
  const [highlightTag, setHighlightTag] = useState<string | null>(null); // 현재 하이라이팅할 태그 id

  /* ----- 상태 ----- */
  const [nodes, setNodes] = useState<NodeMeta[]>([]);
  const [loaded, setLoaded] = useState(false);
  const tagIds = useMemo(() => tags.map(t => t.id), [tags]);
  const explorer = useGraphView(projectId, nodes, tagIds, loaded);
  const view = explorer.view;
  const visibleRef = useRef(view.visible);
  useLayoutEffect(() => { visibleRef.current = view.visible; }, [view.visible]);
  const nodesRef = useRef(nodes);
  const projectIdRef = useRef(projectId);
  useLayoutEffect(() => { projectIdRef.current = projectId; }, [projectId]);
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  const addToCy = useCallback((arr: NodeMeta[]) => {
    const cy = cyInstance.current;
    if (!cy) return;
    const eles: ElementDefinition[] = arr.flatMap((n) => {
      // 이미 width, height가 있으므로 재계산 필요 없음
      return [
        {
          data: { id: n.id, label: n.label, status: n.status, width: n.width, height: n.height, tag: (n.tags ?? []).map(String) },
          position: { x: n.pos_x, y: n.pos_y },
          style: { opacity: n.opacity ?? 1 },
        },
        ...(n.parentId
          ? [{
            data: {
              id: `e-${n.parentId}-${n.id}`,
              source: n.parentId,
              target: n.id,
            },
          }]
          : []),
      ];
    });
    cy.add(eles);
  }, []);

  const updateNodesAndCy = (updater: (nodes: NodeMeta[]) => NodeMeta[]) => {
    setNodes((prev) => {
      const next = updater(prev);
      nodesRef.current = next;
      return next;
    });
};

  const updateLocalNode = (
    nodeId: string,
    updater: (node: NodeMeta) => NodeMeta,
  ) => {
    const next = nodesRef.current.map((node) =>
      node.id === nodeId ? updater(node) : node,
    );
    nodesRef.current = next;
    setNodes(next);
    return next.find((node) => node.id === nodeId);
  };

  const refreshSequence = useRef(0);
  const refreshNodes = useCallback(async (targetProjectId = projectIdRef.current) => {
    const sequence = ++refreshSequence.current;
    const [list, tagList] = await Promise.all([fetchNodes(targetProjectId), listTags(targetProjectId)]);
    if (targetProjectId !== projectIdRef.current || sequence !== refreshSequence.current) {
      return undefined;
    }
    const previousById = new Map(
      nodesRef.current.map((node) => [node.id, node]),
    );
    const metas = list.map((node) =>
      toNodeMeta(node, previousById.get(String(node.id))),
    );

    nodesRef.current = metas;
    setNodes(metas);
    setTags(tagList.map(t => ({ ...t, id: String(t.id) })));
    setLoaded(true);
    return metas;
  }, []);
  useNodeEvents(projectId, refreshNodes);

  const resyncNodes = async (fallback?: () => void) => {
    try {
      await refreshNodes(projectIdRef.current);
    } catch (refreshError) {
      console.error("노드 서버 상태 재동기화 실패", refreshError);
      fallback?.();
    }
  };

  const applyAuthoritativePatchResponse = (saved: NodeOut) => {
    const nodeId = String(saved.id);
    const widthHeight = measureNodeSize(saved.content ?? "");
    const updated = updateLocalNode(nodeId, (node) => ({
      ...node,
      label: saved.content,
      pos_x: saved.pos_x ?? node.pos_x,
      pos_y: saved.pos_y ?? node.pos_y,
      version: saved.version,
      ...widthHeight,
    }));

    const cyNode = cyInstance.current?.$id(nodeId);
    if (cyNode && cyNode.length > 0) {
      cyNode.data({
        label: saved.content,
        width: widthHeight.width,
        height: widthHeight.height,
      });
      cyNode.position({
        x: saved.pos_x ?? updated?.pos_x ?? 0,
        y: saved.pos_y ?? updated?.pos_y ?? 0,
      });
    }
    return updated;
  };


  useEffect(() => {
    refreshNodes(projectId)
      .catch(console.error);
  }, [projectId, refreshNodes]);


  const [ctxNodeId, setCtxNodeId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const showMenu = useNodeMenu();


  //태그 하이라이팅
  useEffect(() => {
    const cy = cyInstance.current;
    if (!cy) return;

    // 모두 초기화(하이라이트 해제)
    cy.nodes().forEach((node) => {
      node.removeClass("highlighted");
    });

    if (highlightTag) {
      cy.nodes().forEach((node) => {
        const nodeData = nodesRef.current.find((n) => n.id === node.id());
        if (nodeData?.tags?.includes(highlightTag)) {
          node.addClass("highlighted");
        }
      });
    }
  }, [highlightTag]);
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
        if (targetProjectId !== projectIdRef.current) return;
        const newTag = { ...t, id: String(t.id) };
        setTags((ts) => [...ts, newTag]);
        realId = newTag.id;
      } catch (e) {
        if (targetProjectId !== projectIdRef.current) return;
        console.error(e);
        return;
      }
    }

    try {
      // 모든 노드에 태그를 attach
      await attachTag(targetProjectId, realId, targetNodeId);
      if (targetProjectId !== projectIdRef.current) return;
      updateNodesAndCy((ns) =>
        ns.map((n) =>
          allNodeIds.includes(n.id)
            ? { ...n, tags: [...(n.tags ?? []), realId] }
            : n
        )
      );
    } catch (e) {
      if (targetProjectId !== projectIdRef.current) return;
      console.error(e);
    }
  };

  const handleRemoveTag = async (tagId: string) => {
    if (!ctxNodeId || !visibleRef.current.has(ctxNodeId)) return;
    const targetProjectId = projectIdRef.current;
    const targetNodeId = ctxNodeId;
    const allNodeIds = [
      targetNodeId,
      ...findChildrenIds(nodesRef.current, targetNodeId),
    ];

    try {
      await detachTag(targetProjectId, tagId, targetNodeId);
      if (targetProjectId !== projectIdRef.current) return;
      updateNodesAndCy((ns) =>
        ns.map((n) =>
          allNodeIds.includes(n.id)
            ? { ...n, tags: (n.tags ?? []).filter((t) => t !== tagId) }
            : n
        )
      );
    } catch (e) {
      if (targetProjectId !== projectIdRef.current) return;
      console.error(e);
    }
  };

  /* ----- AI·빈 노드 생성 로직 ----- */
  const spawning = useRef(new Set<string>());
  const spawnPlans = useRef(new Map<string, ChildCreationPlan>());
  const spawnChildren = async (parent: NodeMeta) => {
    if (parent.generated) return;
    const targetProjectId = projectIdRef.current;
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
        ai: (prompt, payload, key) => apiCreateAINodes(targetProjectId, prompt, payload, key),
        regular: (payload, key) => createNode(targetProjectId, payload, key),
      }, () => targetProjectId === projectIdRef.current);
      if (!complete) return;
      await refreshNodes(targetProjectId);
      if (targetProjectId !== projectIdRef.current) return;
      updateLocalNode(parent.id, (node) => ({ ...node, frozen: true, generated: true }));
      spawnPlans.current.delete(operation);
    } catch (error) {
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
    try {
      await apiActivateNode(targetProjectId, Number(meta.id));
      const refreshed = await refreshNodes(targetProjectId);
      return refreshed?.find((node) => node.id === meta.id);
    } catch (e) {
      console.error(e);
      if (targetProjectId !== projectIdRef.current) return undefined;
      await resyncNodes();
      return undefined;
    }
  };

  /* ───── 헬퍼 ───── */
  // const isNumericId = (s: string) => /^\d+$/.test(s);

  /* ───── handleTap 교체 ───── */
  const handleTap = async (e: cytoscape.EventObject) => {
    const oldId = e.target.id();
    const cur = nodesRef.current.find((n) => n.id === oldId);
    if (!cur || !visibleRef.current.has(oldId)) return;
    const targetProjectId = projectIdRef.current;

    /* 1) AI GHOST (서버에 이미 있음) → 바로 activate */
    if (cur.status === "GHOST") {
      if (cur.label === "?") {
        // 서버에 빈 노드로만 생성된 경우 → 사용자 입력 받아서 내용 갱신
        const input = window.prompt("노드 내용을 입력하세요", cur.label);
        if (!input) return;

        try {
          const saved = await updateNode(targetProjectId, Number(cur.id), {
            content: input,
            pos_x: cur.pos_x,
            pos_y: cur.pos_y,
            expected_version: cur.version,
          });
          if (targetProjectId !== projectIdRef.current) return;

          applyAuthoritativePatchResponse(saved);
          const active = await activateNodeLocal(cur);
          if (active) await spawnChildren(active);
        } catch (err) {
          console.error(err);
          if (targetProjectId !== projectIdRef.current) return;
          await resyncNodes();
        }
      } else {
        // AI 생성된 노드 → 바로 activate
        await activateNodeLocal(cur);
      }
      return;
    }

    /* 3) 이미 ACTIVE + 숫자 ID → 라벨 수정(updateNode) */
    const newLabel = window.prompt("노드 내용을 수정하세요", cur.label);
    if (!newLabel || newLabel === cur.label) return;

    const previousLabel = cur.label;
    const previousWidth = cur.width;
    const previousHeight = cur.height;
    try {
      const saved = await updateNode(targetProjectId, Number(cur.id), {
        content: newLabel,
        expected_version: cur.version,
      });
      if (targetProjectId !== projectIdRef.current) return;
      const updated = applyAuthoritativePatchResponse(saved);

      /* ✅ 내용이 바뀐 첫 클릭이라면 spawnChildren */
      if (!updated?.generated) {
        await spawnChildren(updated ?? cur);
      }

    } catch (err) {
      console.error(err);
      if (targetProjectId !== projectIdRef.current) return;
      await resyncNodes(() => {
        const restored = updateLocalNode(cur.id, (node) => ({
          ...node,
          label: previousLabel,
          width: previousWidth,
          height: previousHeight,
        }));
        if (restored) {
          cyInstance.current?.$id(cur.id).data({
            label: restored.label,
            width: restored.width,
            height: restored.height,
          });
        }
      });
    }
  };




  /* ----- cytoscape init ----- */
  useEffect(() => {
    if (!cyRef.current) return;
    const cy = cytoscape({
      container: cyRef.current,
      elements: [],
      layout: { name: "preset" },
      "style": [
        {
          selector: "node",
          style: {
            "shape": "roundrectangle",
            "background-color": "#eef2ff",
            "border-width": 1,
            "border-color": "#d1d5db", // 테두리 흐리게
            "label": "data(label)",
            "color": "#1e293b",
            "font-weight": 600,
            "font-size": 16,
            "text-valign": "center",
            "text-halign": "center",
            "padding": "14px",
            "width": "data(width)",
            "height": "data(height)",
            "text-wrap": "wrap",
            "text-max-width": "210px",
            "opacity": 0.88,
            "transition-property": "background-color, color, opacity, border-color",
            "transition-duration": 220,
          }
        }
,
        {
          selector: "node[status = 'ACTIVE']",
          style: {
            "opacity": 1,
          },
        }
,
        {
          selector: "node[status = 'GHOST']",
          style: { "background-color": "#f8fafc", color: "#64748b" },
        },
        {
          selector: "node:selected",
          style: {
            "background-color": "#dbeafe",
            "border-color": "#6366f1",
            "border-width": 3,
            "color": "#1e40af",
            "z-index": 9999,
          }
        }
,
        {
          selector: "node.highlighted",
          style: {
            "background-color": "#fef9c3",
            "border-color": "#facc15",
            "border-width": 4,
            "color": "#92400e",
            "transition-duration": 180,
            "z-index": 10000,
          }
        }
,
        {
          "selector": "edge",
          "style": {
            "width": 3.5,
            "line-color": "#b4b8f5",
            "target-arrow-color": "#b4b8f5",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "opacity": 0.8,
          },
        },
      ],
    });

    cyInstance.current = cy;
    addToCy(nodesRef.current);

    cy.on("tap", "node", handleTap);
    //위치 변경시 이벤트
    cy.on("dragfree", "node", async (event) => {
      const node = event.target;
      const id = node.id();
      const pos = node.position();
      const current = nodesRef.current.find((n) => n.id === String(id));
      if (!current || !visibleRef.current.has(String(id))) return;
      const targetProjectId = projectIdRef.current;
      const previousPosition = {
        x: current.pos_x,
        y: current.pos_y,
      };

      try {
        const saved = await updateNode(targetProjectId, id, {
          pos_x: pos.x,
          pos_y: pos.y,
          expected_version: current.version,
        });
        if (targetProjectId !== projectIdRef.current) return;
        applyAuthoritativePatchResponse(saved);
      } catch (err) {
        console.error("노드 위치 업데이트 실패", err);
        if (targetProjectId !== projectIdRef.current) return;
        await resyncNodes(() => {
          const restored = updateLocalNode(String(id), (localNode) => ({
            ...localNode,
            pos_x: previousPosition.x,
            pos_y: previousPosition.y,
          }));
          if (restored) {
            cy.$id(String(id)).position(previousPosition);
          }
        });
      }
    });

    cy.on("cxttap", "node", (ev) => {
      const nodeId = ev.target.id();
      setCtxNodeId(nodeId);
      const nativeEvent = ev.originalEvent;
      if (nativeEvent) {
        nativeEvent.preventDefault();
        nativeEvent.stopPropagation();
        // next tick에 showMenu 실행 (state 반영 이후)
        setTimeout(() => {
          showMenu({
            event: nativeEvent,
            props: { nodeId },
          });
        }, 0);
      }
    });

    return () => {
      cy.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update the canvas in one batch; searching only changes visibility, never positions.
  useEffect(() => {
    const cy = cyInstance.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().remove();
      addToCy(nodes);
    });
  }, [nodes, addToCy]);
  useEffect(() => {
    const cy = cyInstance.current;
    if (!cy) return;
    const byId = new Map(nodes.map(n => [n.id, n]));
    cy.batch(() => {
      cy.nodes().forEach(n => {
        const visible = view.visible.has(n.id());
        if (n.style("display") !== (visible ? "element" : "none")) n.style("display", visible ? "element" : "none");
        if (!visible && n.selected()) n.unselect();
        const opacity = view.filtering && !view.matches.has(n.id()) ? 0.22 : n.data("status") === "GHOST" ? 0.3 : 1;
        if (Number(n.style("opacity")) !== opacity) n.style("opacity", opacity);
        const source = byId.get(n.id());
        const count = view.hiddenCounts.get(n.id()) ?? 0;
        const label = `${source?.label ?? ""}${view.collapsed.has(n.id()) && !view.expanded.has(n.id()) && count ? ` (+${count})` : ""}`;
        if (n.data("label") !== label) n.data("label", label);
      });
      // Cytoscape automatically hides incident edges when either endpoint has display:none.
      if (explorer.focus && view.visible.has(explorer.focus)) cy.$id(explorer.focus).select();
    });
  }, [view, nodes, explorer.focus]);
  useEffect(() => {
    const cy = cyInstance.current;
    if (cy && explorer.focus && view.visible.has(explorer.focus)) {
      cy.center(cy.$id(explorer.focus));
    }
  }, [explorer.focus, view.visible]);

  const handleSaveImage = () => {
  if (!cyInstance.current) return;
  const blob = cyInstance.current.png({ output: "blob", bg: "white", scale: 2 });

  if (blob instanceof Blob) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "graph.png";
    a.click();
    URL.revokeObjectURL(url);
  }
};

  /* ----- 렌더 ----- */
  return (
    <div className="relative h-full w-full">
      <GraphExplorer explorer={explorer} tags={tags} loaded={loaded} onFocus={() => undefined} />
      <ProjectFiles projectId={projectId} nodes={nodes} />
      <OperationPanel key={`${projectId}:${deleteId ?? ""}`} projectId={projectId} deleteId={deleteId}
        closeDelete={() => setDeleteId(null)} refresh={() => refreshNodes(projectId)} />
      <div
        ref={cyRef}
        data-testid="idea-graph"
        style={{
          width: "100%",
          height: "100%",
          background: "linear-gradient(135deg, #f0f4ff 0%, #f9fafe 100%)",
        }}
      />
      <ul className="sr-only" aria-label="그래프 노드">
        {nodes.filter(n => view.visible.has(n.id)).map((node) => <li key={node.id} data-node-id={node.id}>{node.label}</li>)}
      </ul>
      {/* 플로팅 버튼 */}
      <button
        style={{
          position: "absolute",
          bottom: 28,
          right: 32,
          zIndex: 10,
          padding: "12px 30px",
          borderRadius: "9999px",
          background: "linear-gradient(135deg, #6366f1 60%, #a78bfa 100%)",
          color: "white",
          fontWeight: 800,
          fontSize: 20,
          letterSpacing: 2,
          boxShadow: "0 4px 18px 0 rgba(99,102,241,0.13)",
          border: "none",
          cursor: "pointer",
          transition: "filter .18s",
          textTransform: "uppercase",
        }}
        onClick={() => setTagPopoverOpen((open) => !open)}
      >
        TAG
      </button>

        <button
    style={{
      position: "absolute",
      bottom: 28,
      right: 160, // TAG 버튼보다 왼쪽으로
      zIndex: 10,
      padding: "12px 30px",
      borderRadius: "9999px",
      background: "linear-gradient(135deg, #10b981 60%, #34d399 100%)",
      color: "white",
      fontWeight: 800,
      fontSize: 20,
      letterSpacing: 2,
      boxShadow: "0 4px 18px 0 rgba(16,185,129,0.15)",
      border: "none",
      cursor: "pointer",
      transition: "filter .18s",
      textTransform: "uppercase",
    }}
    onClick={handleSaveImage}
  >
    SAVE
  </button>

      {/* 태그 리스트 팝오버 */}
      {
        tagPopoverOpen && (
          <div
            className="absolute bottom-[84px] right-8 z-30 bg-white rounded-xl shadow-xl border w-56 flex flex-col p-2"
            style={{ animation: "fadeIn .22s" }}
          >
            {tags.length === 0 ? (
              <div className="py-6 text-center text-gray-400">태그 없음</div>
            ) : (
              tags.map((tag) => (
                <button
                  key={tag.id}
                  className={`
              w-full px-4 py-2 my-1 rounded text-left font-medium
              ${highlightTag === tag.id ? "bg-indigo-100 text-indigo-700" : "hover:bg-gray-50"}
            `}
                  onClick={() =>
                    setHighlightTag((prev) => (prev === tag.id ? null : tag.id))
                  }
                >
                  {tag.name}
                </button>
              ))
            )}
          </div>
        )
      }

      <NodeContextMenu
        tags={tags}
        nodeTags={
          ctxNodeId
            ? nodes.find((n) => n.id === ctxNodeId)?.tags ?? []
            : []
        }
        onAdd={handleAddTag}
        onRemove={handleRemoveTag}
        onDelete={() => { if (ctxNodeId && view.visible.has(ctxNodeId)) setDeleteId(ctxNodeId); }}
        onCollapse={() => { if (ctxNodeId) explorer.toggle(ctxNodeId); }}
        onCreate={async () => {
          const parent = nodesRef.current.find(n => n.id === ctxNodeId);
          if (!parent || !view.visible.has(parent.id)) return;
          const content = window.prompt("새 자식 노드의 내용을 입력하세요");
          if (!content?.trim()) return;
          try {
            await createNode(projectId, { content, parent_id: Number(parent.id), depth: parent.depth + 1,
              pos_x: parent.pos_x + 180, pos_y: parent.pos_y + 120 });
            await refreshNodes(projectId);
          } catch { window.alert("노드를 만들지 못했어요. 변경 기록과 연결 상태를 확인해 주세요."); }
        }}
      />
    </div>
  );

}
