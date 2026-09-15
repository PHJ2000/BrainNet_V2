"use client";
import { useRef, useState } from "react";
import { useGraphView } from "./useGraphView";
import { ViewNode } from "./graphView";
type Explorer = ReturnType<typeof useGraphView<ViewNode>>;
const button = "rounded border px-2 py-1 text-sm hover:bg-indigo-50 focus-visible:outline-2 focus-visible:outline-indigo-600";

export default function GraphExplorer({ explorer: e, tags, loaded, onFocus }: {
  explorer: Explorer; tags: { id: string; name: string }[]; loaded: boolean; onFocus: (id: string) => void;
}) {
  const composing = useRef(false);
  const [limit, setLimit] = useState(40);
  return <aside aria-label="노드 탐색" className="absolute left-4 top-4 z-10 w-64 rounded-lg border bg-white/95 p-3 shadow-sm">
    <label className="block text-sm font-semibold" htmlFor="node-search">노드 검색</label>
    <input id="node-search" type="search" value={e.input} placeholder="본문 검색"
      className="my-2 w-full rounded border px-2 py-1.5 focus-visible:outline-2 focus-visible:outline-indigo-600"
      onCompositionStart={() => { composing.current = true; }}
      onCompositionEnd={ev => { composing.current = false; e.setQuery(ev.currentTarget.value); }}
      onChange={ev => { e.setInput(ev.target.value); if (!composing.current) e.setQuery(ev.target.value); }} />
    {!!tags.length && <fieldset className="mb-2 flex max-h-24 flex-wrap gap-1 overflow-auto">
      <legend className="text-xs text-slate-600">태그 중 하나 일치</legend>
      {tags.map(t => <button key={t.id} aria-pressed={e.tags.includes(t.id)} onClick={() => e.toggleTag(t.id)}
        className={`${button} ${e.tags.includes(t.id) ? "bg-indigo-100" : ""}`}>{t.name}</button>)}
    </fieldset>}
    <div className="flex items-center justify-between gap-2">
      <p aria-live="polite" data-testid="search-count" className="text-sm">{e.view.filtering ? `검색 결과 ${e.view.results.length}개` : `전체 ${e.view.nodes.length}개`}</p>
      <button className={button} onClick={e.clear}>전체 해제</button>
    </div>
    {!loaded ? <p className="mt-3 text-sm">노드를 불러오는 중…</p> : !e.view.nodes.length ?
      <p className="mt-3 text-sm">프로젝트에 노드가 없어요.</p> : !e.view.results.length ?
        <p className="mt-3 text-sm">조건에 맞는 노드가 없어요.</p> : <>
          <ul aria-label="탐색 결과" className="mt-2 max-h-[38vh] overflow-auto">
            {e.view.results.slice(0, limit).map(n => <li key={n.id} className="flex items-center gap-1 border-t py-1" data-result-id={n.id}>
              <button className="min-w-0 flex-1 truncate rounded p-1 text-left text-sm focus-visible:outline-2 focus-visible:outline-indigo-600"
                title={n.label} onClick={() => { e.setFocus(n.id); onFocus(n.id); }}>{n.label}</button>
              {(e.view.hiddenCounts.get(n.id) ?? 0) > 0 && <button className={button} disabled={!e.ready || !e.view.visible.has(n.id)}
                aria-label={`${n.label} ${e.view.collapsed.has(n.id) ? "펼치기" : "접기"}`} aria-expanded={!e.view.collapsed.has(n.id)}
                onClick={() => e.toggle(n.id)}>{e.view.collapsed.has(n.id) ? `+${e.view.hiddenCounts.get(n.id)}` : "접기"}</button>}
            </li>)}
          </ul>
          {e.view.results.length > limit && <button className={`${button} mt-2`} onClick={() => setLimit(v => v + 40)}>결과 더 보기</button>}
        </>}
  </aside>;
}
