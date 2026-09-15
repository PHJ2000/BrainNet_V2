"use client";

import { useEffect } from "react";
import { apiClient } from "@/lib/apiClient";

/** Invalidation reloads authorized state; duplicate events never append duplicate nodes. */
export function useNodeEvents(projectId: number, reload: (projectId: number) => Promise<unknown>) {
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    let stopped = false;
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let refresh: ReturnType<typeof setTimeout> | undefined;
    let delay = 500;
    let reloading = false;
    let dirty = false;

    const invalidate = () => {
      if (stopped || refresh) return;
      if (reloading) { dirty = true; return; }
      refresh = setTimeout(() => {
        refresh = undefined;
        reloading = true;
        void reload(projectId).catch(console.error).finally(() => {
          reloading = false;
          if (dirty) { dirty = false; invalidate(); }
        });
      }, 100);
    };
    const connect = () => {
      if (stopped) return;
      const base = new URL(apiClient.defaults.baseURL || window.location.origin, window.location.origin);
      base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
      base.pathname = `${base.pathname.replace(/\/$/, "")}/projects/${projectId}/ws`;
      base.searchParams.set("token", token);
      const currentSocket = new WebSocket(base);
      socket = currentSocket;
      currentSocket.onopen = () => { delay = 500; invalidate(); };
      currentSocket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (["node.created", "node.updated", "node.deleted", "tags.updated", "resync.required"].includes(message.type)) invalidate();
        } catch { /* Ignore unrelated protocol messages. */ }
      };
      currentSocket.onclose = (event) => {
        if (stopped || event.code === 4401 || event.code === 4403) return;
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 10000);
      };
      currentSocket.onerror = () => currentSocket.close();
    };
    connect();
    // A lost notification/half-open connection is healed from the authoritative DB.
    const reconcile = setInterval(invalidate, 30000);
    return () => {
      stopped = true;
      clearInterval(reconcile);
      if (retry) clearTimeout(retry);
      if (refresh) clearTimeout(refresh);
      socket?.close();
    };
  }, [projectId, reload]);
}
