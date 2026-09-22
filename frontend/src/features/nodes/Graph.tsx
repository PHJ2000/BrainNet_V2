"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, memo } from "react";
import cytoscape, { Core, ElementDefinition } from "cytoscape";
import { useGraphActions } from "./useGraphActions";
import { useGraphData } from "./useGraphData";
import { measureNodeSize, type NodeMeta, type Tag } from "./graphModel";
export type { NodeMeta, Tag } from "./graphModel";
import OperationPanel from "./OperationPanel";
import GraphExplorer from "./GraphExplorer";
import { useGraphView } from "./useGraphView";
import ProjectFiles from "@/features/projects/ProjectFiles";
import {
  NodeOut,
  createNode,        // ✅ 추가
  updateNode,        // ✅ 추가
} from "./nodeApi";  // ← 변경
import {
  Menu,
  Item,
  Submenu,
  useContextMenu,
} from "react-contexify";
import "react-contexify/ReactContexify.css";

/* ───────────── 타입 ───────────── */
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
/* ──────────── 그래프 컴포넌트 ─────────── */
export default function Graph({ projectId }: GraphProps) {
  const cyRef = useRef<HTMLDivElement>(null);
  const cyInstance = useRef<Core | null>(null);
  const data = useGraphData(projectId);
  const { nodes, nodesRef, tags, loaded, projectIdRef, getScope, refreshNodes,
    updateLocalNode, resyncNodes } = data;
  const [tagPopoverOpen, setTagPopoverOpen] = useState(false); // 태그 팝오버/모달
  const [highlightTag, setHighlightTag] = useState<string | null>(null); // 현재 하이라이팅할 태그 id

  /* ----- 상태 ----- */
  const tagIds = useMemo(() => tags.map(t => t.id), [tags]);
  const explorer = useGraphView(projectId, nodes, tagIds, loaded);
  const view = explorer.view;
  const visibleRef = useRef(view.visible);
  useLayoutEffect(() => { visibleRef.current = view.visible; }, [view.visible]);
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

  const applyAuthoritativePatchResponse = (saved: NodeOut) => {
    const nodeId = String(saved.id);
    const current = nodesRef.current.find(node => node.id === nodeId);
    if (current && current.version > saved.version) return current;
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
  }, [highlightTag, nodesRef]);
  const { handleAddTag, handleRemoveTag, spawnChildren, activateNodeLocal } =
    useGraphActions(data, ctxNodeId, visibleRef);

  /* ───── 헬퍼 ───── */
  // const isNumericId = (s: string) => /^\d+$/.test(s);

  /* ───── handleTap 교체 ───── */
  const handleTap = async (e: cytoscape.EventObject) => {
    const oldId = e.target.id();
    const cur = nodesRef.current.find((n) => n.id === oldId);
    if (!cur || !visibleRef.current.has(oldId)) return;
    const targetProjectId = projectIdRef.current;
    const scope = getScope();
    if (!scope.isCurrent()) return;

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
          }, scope.signal);
          if (!scope.isCurrent()) return;

          applyAuthoritativePatchResponse(saved);
          const active = await activateNodeLocal(cur);
          if (active) await spawnChildren(active);
        } catch (err) {
          console.error(err);
          if (!scope.isCurrent()) return;
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
      }, scope.signal);
      if (!scope.isCurrent()) return;
      const updated = applyAuthoritativePatchResponse(saved);

      /* ✅ 내용이 바뀐 첫 클릭이라면 spawnChildren */
      if (!updated?.generated) {
        await spawnChildren(updated ?? cur);
      }

    } catch (err) {
      console.error(err);
      if (!scope.isCurrent()) return;
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
    const scope = getScope();
    if (!scope.isCurrent()) return;
      const previousPosition = {
        x: current.pos_x,
        y: current.pos_y,
      };

      try {
        const saved = await updateNode(targetProjectId, id, {
          pos_x: pos.x,
          pos_y: pos.y,
          expected_version: current.version,
        }, scope.signal);
        if (!scope.isCurrent()) return;
        applyAuthoritativePatchResponse(saved);
      } catch (err) {
        console.error("노드 위치 업데이트 실패", err);
        if (!scope.isCurrent()) return;
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
  if (data.accessError) return <div role="alert" className="p-6">{data.accessError}</div>;
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
          const scope = getScope();
          if (!scope.isCurrent()) return;
          try {
            await createNode(projectId, { content, parent_id: Number(parent.id), depth: parent.depth + 1,
              pos_x: parent.pos_x + 180, pos_y: parent.pos_y + 120 }, undefined, scope.signal);
            await refreshNodes(projectId);
          } catch { if (!scope.isCurrent()) return; window.alert("노드를 만들지 못했어요. 변경 기록과 연결 상태를 확인해 주세요."); }
        }}
      />
    </div>
  );

}
