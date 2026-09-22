"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, memo } from "react";
import cytoscape, { Core, ElementDefinition, NodeSingular, EdgeSingular } from "cytoscape";
import { useGraphActions } from "./useGraphActions";
import { useGraphData } from "./useGraphData";
import { useGraphEditing } from "./useGraphEditing";
import { type NodeMeta, type Tag } from "./graphModel";
export type { NodeMeta, Tag } from "./graphModel";
import NodeEditor from "./NodeEditor";
import OperationPanel from "./OperationPanel";
import GraphExplorer from "./GraphExplorer";
import { useGraphView } from "./useGraphView";
import ProjectFiles from "@/features/projects/ProjectFiles";
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
  readOnly?: boolean;
  aiEnabled?: boolean;
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
  onGenerate: () => void;
  readOnly: boolean;
  aiEnabled: boolean;
}

const NodeContextMenu = memo(function NodeContextMenu({
  tags,
  nodeTags,
  onAdd,
  onRemove,
  onDelete,
  onCreate,
  onCollapse, onGenerate, readOnly, aiEnabled,
}: CtxProps) {
  return (
    <Menu id={NODE_MENU_ID} animation="fade">
      <Item disabled={readOnly} onClick={onCreate}>자식 노드 추가…</Item>
      <Item disabled={readOnly || !aiEnabled} onClick={onGenerate}>AI 아이디어 생성</Item>
      <Item onClick={onCollapse}>가지 접기 / 펼치기</Item>
      <Item disabled={readOnly} onClick={onDelete}>가지 삭제…</Item>
      <Submenu disabled={readOnly} label="태그 달기…">
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
        <Submenu disabled={readOnly} label="태그 떼기…">
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
export default function Graph({ projectId, readOnly = false, aiEnabled = false }: GraphProps) {
  const cyRef = useRef<HTMLDivElement>(null);
  const cyInstance = useRef<Core | null>(null);
  const data = useGraphData(projectId);
  const { nodes, nodesRef, tags, loaded, refreshNodes } = data;
  const [tagPopoverOpen, setTagPopoverOpen] = useState(false); // 태그 팝오버/모달
  const [highlightTag, setHighlightTag] = useState<string | null>(null); // 현재 하이라이팅할 태그 id

  /* ----- 상태 ----- */
  const tagIds = useMemo(() => tags.map(t => t.id), [tags]);
  const explorer = useGraphView(projectId, nodes, tagIds, loaded);
  const view = explorer.view;
  const visibleRef = useRef(view.visible);
  const canvasSnapshot = useRef(new Map<string, NodeMeta>());
  const displaySnapshot = useRef(new Map<string, { visible: boolean; opacity: number }>());
  const edgeVisibility = useRef(new Map<string, boolean>());
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
  const actions = useGraphActions(data, ctxNodeId, visibleRef);
  const { handleAddTag, handleRemoveTag } = actions;
  const editing = useGraphEditing(data, actions, cyInstance, visibleRef, readOnly);
  const { save } = editing;

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

    cy.on("tap", "node", editing.handleTap);
    //위치 변경시 이벤트
    cy.on("dragfree", "node", editing.handleDrag);

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

  useEffect(() => { cyInstance.current?.autoungrabify(readOnly); }, [readOnly]);

  // Update the canvas in one batch; searching only changes visibility, never positions.
  useEffect(() => {
    const cy = cyInstance.current;
    if (!cy) return;
    cy.batch(() => {
      const ids = new Set(nodes.map(n => n.id));
      cy.nodes().filter(n => !ids.has(n.id())).remove();
      for (const id of displaySnapshot.current.keys()) if (!ids.has(id)) displaySnapshot.current.delete(id);
      const added = nodes.filter(n => !cy.$id(n.id).length);
      const addedIds = new Set(added.map(n => n.id));
      addToCy(added);
      for (const node of nodes) {
        if (addedIds.has(node.id)) continue;
        const previous = canvasSnapshot.current.get(node.id);
        if (previous === node) continue;
        const element = cy.$id(node.id);
        if (!element.length) { addToCy([node]); continue; }
        element.data({ label: node.label, status: node.status, width: node.width, height: node.height, tag: node.tags ?? [] });
        element.position({ x: node.pos_x, y: node.pos_y });
        if (previous?.parentId !== node.parentId) {
          element.incomers("edge").remove();
          if (node.parentId) cy.add({ data: { id: `e-${node.parentId}-${node.id}`, source: node.parentId, target: node.id } });
        }
      }
      canvasSnapshot.current = new Map(nodes.map(n => [n.id, n]));
      const edgeIds = new Set(cy.edges().map(edge => edge.id()));
      for (const id of edgeVisibility.current.keys()) if (!edgeIds.has(id)) edgeVisibility.current.delete(id);
    });
  }, [nodes, addToCy]);
  useEffect(() => {
    const cy = cyInstance.current;
    if (!cy) return;
    const byId = new Map(nodes.map(n => [n.id, n]));
    // Empty results hide the canvas as a whole. Keep the last per-node display
    // state so returning to results does not restyle thousands of unchanged nodes.
    if (!view.visible.size) { cy.$(":selected").unselect(); return; }
    cy.batch(() => {
      const show: NodeSingular[] = [], hide: NodeSingular[] = [];
      const opacityGroups = new Map<number, NodeSingular[]>();
      cy.nodes().forEach(n => {
        const visible = view.visible.has(n.id());
        const previous = displaySnapshot.current.get(n.id());
        if (previous?.visible !== visible) (visible ? show : hide).push(n);
        if (!visible && n.selected()) n.unselect();
        const opacity = view.filtering && !view.matches.has(n.id()) ? 0.22 : n.data("status") === "GHOST" ? 0.3 : 1;
        if (previous?.opacity !== opacity) {
          const group = opacityGroups.get(opacity) ?? [];
          group.push(n); opacityGroups.set(opacity, group);
        }
        displaySnapshot.current.set(n.id(), { visible, opacity });
        const source = byId.get(n.id());
        const count = view.hiddenCounts.get(n.id()) ?? 0;
        const label = `${source?.label ?? ""}${view.collapsed.has(n.id()) && !view.expanded.has(n.id()) && count ? ` (+${count})` : ""}`;
        if (n.data("label") !== label) n.data("label", label);
      });
      // A scratch setter also recalculates Cytoscape styles. Keep our cache outside
      // Cytoscape and notify the renderer once per changed style group.
      // Fixed positions can retain geometry when hidden. display:none invalidates
      // endpoint/parallel-edge bounds and recomputes curves for the whole branch.
      if (show.length) cy.collection(show).style("visibility", "visible");
      if (hide.length) cy.collection(hide).style("visibility", "hidden");
      for (const [opacity, group] of opacityGroups) cy.collection(group).style("opacity", opacity);
      // visibility does not inherit across edges: hide edges explicitly as well.
      const showEdges: EdgeSingular[] = [], hideEdges: EdgeSingular[] = [];
      cy.edges().forEach(edge => {
        const visible = view.visible.has(edge.data("source")) && view.visible.has(edge.data("target"));
        if (edgeVisibility.current.get(edge.id()) !== visible) (visible ? showEdges : hideEdges).push(edge);
        edgeVisibility.current.set(edge.id(), visible);
      });
      if (showEdges.length) cy.collection(showEdges).style("visibility", "visible");
      if (hideEdges.length) cy.collection(hideEdges).style("visibility", "hidden");
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
      <div aria-label="동기화 상태" className="absolute bottom-4 left-4 z-30 max-w-md rounded-lg border bg-white/95 p-3 shadow-sm">
        <p role="status" className="text-sm">{readOnly ? "읽기 전용 · " : ""}{data.connection} · {save.state.message}</p>
        {save.state.detail && <p className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap text-sm text-slate-600">{save.state.detail}</p>}
        {save.state.kind === "failed" && <button className="mt-2 rounded border px-3 py-1 text-sm" onClick={() => void save.retry()}>저장 다시 시도</button>}
        {save.state.kind === "conflict" && <button className="mt-2 rounded border px-3 py-1 text-sm" onClick={() => void refreshNodes(projectId, true).catch(() => undefined)}>최신 상태 확인</button>}
        {["failed", "conflict"].includes(save.state.kind) && <button className="ml-2 text-sm underline" onClick={editing.discard}>입력 버리기</button>}
      </div>
      {editing.draft && !editing.open && <button onClick={editing.resume} className="absolute bottom-28 left-4 z-30 rounded border bg-white px-4 py-2">초안 이어쓰기</button>}
      <NodeEditor editing={editing} />
      {actions.tagSave.state.kind !== "idle" && <div role="status" className="absolute bottom-44 left-4 z-30 max-w-sm rounded border bg-white p-3 text-sm">태그 · {actions.tagSave.state.message}
        <p>{actions.tagSave.state.detail}</p>
        {actions.tagSave.state.kind === "failed" && <button onClick={() => void actions.tagSave.retry()} className="mt-2 rounded border px-2 py-1">태그 다시 시도</button>}
        {!["saving"].includes(actions.tagSave.state.kind) && <button className="ml-2 underline" onClick={actions.tagSave.discard}>안내 닫기</button>}
      </div>}
      {!aiEnabled && <p className="absolute right-4 top-16 z-10 text-xs text-slate-500">수동 작성 모드 · AI 생성은 설정 후 사용할 수 있습니다.</p>}
      {data.loadError && <div role="alert" className="absolute left-4 top-20 z-40 max-w-md rounded border border-red-200 bg-white p-4 shadow">
        <p>{data.loadError}</p><button disabled={data.loading} onClick={() => void refreshNodes(projectId).catch(() => undefined)} className="mt-2 rounded border px-3 py-1">노드 다시 불러오기</button>
      </div>}
      <GraphExplorer explorer={explorer} tags={tags} loaded={loaded} onFocus={() => undefined} />
      <ProjectFiles projectId={projectId} nodes={nodes} />
      <OperationPanel readOnly={readOnly} key={`${projectId}:${deleteId ?? ""}`} projectId={projectId} deleteId={deleteId}
        closeDelete={() => setDeleteId(null)} refresh={() => refreshNodes(projectId)} />
      <div
        ref={cyRef}
        data-testid="idea-graph"
        style={{
          width: "100%",
          height: "100%",
          visibility: view.visible.size ? "visible" : "hidden",
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

      <NodeContextMenu readOnly={readOnly} aiEnabled={aiEnabled}
        onGenerate={() => { const node = nodesRef.current.find(n => n.id === ctxNodeId); if (node && aiEnabled && !readOnly) void editing.generate(node); }}
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
        onCreate={() => {
          const parent = nodesRef.current.find(n => n.id === ctxNodeId);
          if (parent && view.visible.has(parent.id)) void editing.addChild(parent);
        }}
      />
    </div>
  );

}
