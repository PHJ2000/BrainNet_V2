"use client";
import { useRef, useState } from "react";
import axios from "axios";

type Scope = { isCurrent: () => boolean };
type Pending = { action: () => Promise<unknown>; detail: string; scope: Scope };
export function useSaveOperation(getScope: () => Scope) {
  const pending = useRef<Pending | null>(null);
  const busy = useRef(false);
  const [state, setState] = useState({ kind: "idle", detail: "", message: "변경 없음" });
  const execute = async (operation: Pending) => {
    if (busy.current || !operation.scope.isCurrent()) return false;
    busy.current = true;
    setState({ kind: "saving", detail: operation.detail, message: "저장 중" });
    try {
      await operation.action();
      if (!operation.scope.isCurrent()) return false;
      pending.current = null;
      setState({ kind: "saved", detail: "", message: "저장 완료" });
      return true;
    } catch (error) {
      if (!operation.scope.isCurrent() || axios.isCancel(error)) return false;
      const conflict = axios.isAxiosError(error) && error.response?.status === 409 &&
        error.response?.data?.code !== "IDEMPOTENCY_IN_PROGRESS";
      setState({ kind: conflict ? "conflict" : "failed", detail: operation.detail,
        message: conflict ? "다른 변경과 충돌했습니다. 최신 상태를 확인해 주세요." : "저장하지 못했습니다. 입력은 유지됩니다." });
      return false;
    } finally { busy.current = false; }
  };
  const run = async (action: () => Promise<unknown>, detail = "") => {
    if (pending.current || busy.current) return false;
    const operation = { action, detail, scope: getScope() };
    pending.current = operation;
    return execute(operation);
  };
  return { state, run, isBlocked: () => !!pending.current || busy.current,
    retry: () => pending.current ? execute(pending.current) : Promise.resolve(false),
    discard: () => { if (!busy.current) { pending.current = null; setState({ kind: "idle", detail: "", message: "변경 없음" }); } } };
}
