"use client";
import { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/apiClient";
import { graphView, ViewNode } from "./graphView";

export function useGraphView<T extends ViewNode>(projectId: number, nodes: T[], tagIds: string[], loaded = false) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ key: string; collapsed: string[] } | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const { data } = await apiClient.get<{ id: number }>("/users/me");
      const key = `brainnet:view:${data.id}:${projectId}`;
      let collapsed: string[] = [];
      try { const stored: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
        if (Array.isArray(stored)) collapsed = stored.filter((v): v is string => typeof v === "string");
      } catch { /* Corrupt/unavailable local storage does not prevent graph use. */ }
      if (!cancelled) { setSaved({ key, collapsed }); setFocus(null); setInput(""); setQuery(""); setSelectedTags([]); }
    };
    const accountChanged = (e: StorageEvent) => { if (e.key === "token") void load().catch(() => setSaved(null)); };
    void load().catch(() => { if (!cancelled) setSaved(null); });
    window.addEventListener("storage", accountChanged);
    return () => { cancelled = true; window.removeEventListener("storage", accountChanged); };
  }, [projectId]);
  const tags = useMemo(() => selectedTags.filter(id => tagIds.includes(id)), [selectedTags, tagIds]);
  const view = useMemo(() => graphView(nodes, query, tags, saved?.collapsed ?? [], focus), [nodes, query, tags, saved, focus]);
  useEffect(() => {
    // Also prune the last removed ID, but never during the initial loading frame.
    if (saved && loaded) {
      try { localStorage.setItem(saved.key, JSON.stringify([...view.collapsed])); } catch { /* Private mode/quota. */ }
    }
  }, [saved, loaded, view.collapsed]);
  const toggle = (id: string) => {
    if (!view.visible.has(id)) return;
    setSaved(s => s ? { ...s, collapsed: s.collapsed.includes(id) ? s.collapsed.filter(n => n !== id) : [...s.collapsed, id] } : s);
  };
  const clear = () => { setInput(""); setQuery(""); setSelectedTags([]); setFocus(null); setSaved(s => s ? { ...s, collapsed: [] } : s); };
  return { view, input, setInput, setQuery, tags, focus, setFocus, toggle, clear, ready: !!saved,
    toggleTag: (id: string) => setSelectedTags(s => s.includes(id) ? s.filter(t => t !== id) : [...s, id]) };
}
