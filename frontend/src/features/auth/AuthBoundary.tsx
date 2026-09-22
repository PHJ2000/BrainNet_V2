"use client";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";

const subscribe = () => () => {};
const hasToken = () => !!localStorage.getItem("token");
const serverSnapshot = () => false;

export default function AuthBoundary({ children }: { children: ReactNode }) {
  const ready = useSyncExternalStore(subscribe, hasToken, serverSnapshot);
  useEffect(() => {
    if (!localStorage.getItem("token")) {
      window.location.replace("/login");
      return;
    }
    const syncSession = (event: StorageEvent) => {
      if ((event.key === "token" && event.newValue !== event.oldValue) || event.key === null) {
        // Never retain another account's cache after a login/logout in another tab.
        window.location.replace(localStorage.getItem("token") ? "/dashboard" : "/login");
      }
    };
    window.addEventListener("storage", syncSession);
    return () => window.removeEventListener("storage", syncSession);
  }, []);
  return ready ? children : <p className="p-6">로그인 확인 중...</p>;
}
