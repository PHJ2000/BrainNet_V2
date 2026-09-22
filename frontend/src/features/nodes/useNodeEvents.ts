"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/apiClient";

/** Invalidation reloads authorized state; duplicate events never append duplicate nodes. */
export function useNodeEvents(projectId: number, reload: (projectId: number) => Promise<unknown>) {
  const [accessError, setAccessError] = useState<{ projectId: number; message: string } | null>(null);
  const [connection, setConnection] = useState("연결 중");
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
      currentSocket.onopen = () => { delay = 500; setConnection("연결됨"); };
      currentSocket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "ping") { currentSocket.send("pong"); return; }
          if (message.type === "project.membership_updated") window.dispatchEvent(new Event("brainnet:membership"));
          if (["project.membership_updated", "node.created", "node.updated", "node.deleted", "tags.updated", "resync.required"].includes(message.type)) invalidate();
        } catch { /* Ignore unrelated protocol messages. */ }
      };
      currentSocket.onclose = (event) => {
        if (stopped) return;
        if (event.code === 4401 || event.code === 4403) {
          stopped = true;
          setConnection("접근 종료");
          clearInterval(reconcile);
          if (refresh) clearTimeout(refresh);
          if (event.code === 4401 && localStorage.getItem("token") === token) {
            localStorage.removeItem("token");
            window.location.replace("/login?expired=1");
          } else {
            setAccessError({ projectId, message: "프로젝트 접근 권한이 없거나 삭제되었습니다. 프로젝트 목록으로 돌아가 주세요." });
          }
          return;
        }
        setConnection("재연결 중");
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 10000);
      };
      currentSocket.onerror = () => currentSocket.close();
    };
    connect();
    // A lost notification/half-open connection is healed from the authoritative DB.
    let ticks = 0;
    const reconcile = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (socket?.readyState !== WebSocket.OPEN || ++ticks % 4 === 0) invalidate();
    }, 30000);
    const onVisible = () => { if (document.visibilityState === "visible") invalidate(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      clearInterval(reconcile);
      document.removeEventListener("visibilitychange", onVisible);
      if (retry) clearTimeout(retry);
      if (refresh) clearTimeout(refresh);
      socket?.close();
    };
  }, [projectId, reload]);
  return { accessError: accessError?.projectId === projectId ? accessError.message : null, connection };
}
