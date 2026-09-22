"use client";
import { useCallback, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/apiClient";

const eventName = "brainnet:workspace-draft";
const subscribe = (callback: () => void) => {
  window.addEventListener(eventName, callback);
  window.addEventListener("storage", callback);
  return () => { window.removeEventListener(eventName, callback); window.removeEventListener("storage", callback); };
};
function slot() {
  try {
    const key = "brainnet:workspace-tab";
    let id = sessionStorage.getItem(key);
    if (!id) { id = crypto.randomUUID(); sessionStorage.setItem(key, id); }
    return id;
  } catch { return "storage-unavailable"; }
}
export type Draft<T> = { item: T; attempted: boolean };

/** One draft per form type, account, project and browser tab. No token is saved. */
export function useWorkspaceDraft<T extends {id: string}>(projectId: number, kind: string) {
  const me = useQuery({ queryKey: ["me"], queryFn: async () => (await apiClient.get<{id: number}>("/users/me")).data });
  const prefix = me.data ? `brainnet:workspace-draft:${me.data.id}:${projectId}:${kind}:` : null;
  const snapshot = useCallback(() => {
    if (!prefix) return "";
    try { return localStorage.getItem(prefix + slot()) ?? ""; } catch { return ""; }
  }, [prefix]);
  const raw = useSyncExternalStore(subscribe, snapshot, () => "");
  let draft: Draft<T> | null = null;
  try { const value = JSON.parse(raw); if (typeof value?.item?.id === "string" && typeof value.attempted === "boolean") draft = value; } catch { /* no usable draft */ }
  const save = useCallback((value: Draft<T>) => {
    if (!prefix) return false;
    try {
      const key = prefix + slot(), json = JSON.stringify(value);
      if (localStorage.getItem(key) !== json) { localStorage.setItem(key, json); window.dispatchEvent(new Event(eventName)); }
      return true;
    } catch { return false; }
  }, [prefix]);
  const discard = useCallback(() => {
    if (!prefix) return;
    try { localStorage.removeItem(prefix + slot()); window.dispatchEvent(new Event(eventName)); } catch { /* unavailable storage */ }
  }, [prefix]);
  return { draft, save, discard, ready: !!me.data };
}
