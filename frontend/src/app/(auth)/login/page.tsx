// app/(auth)/login/page.tsx
"use client";

import { useState, useSyncExternalStore } from "react";
import { useAuth } from "@/features/auth/useAuth";

const subscribe = () => () => {};
const expiredSnapshot = () => new URLSearchParams(window.location.search).get("expired") === "1";
const serverSnapshot = () => false;

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { handleLogin, error } = useAuth();
  const expired = useSyncExternalStore(subscribe, expiredSnapshot, serverSnapshot);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleLogin(email, password);
  };

  return (
    <form onSubmit={onSubmit} className="space-y-7">
      <h1 className="text-2xl font-bold text-center text-gray-800 mb-4">로그인</h1>
      {expired && <p role="status" className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">로그인이 만료되었습니다. 다시 로그인해 주세요.</p>}

      <div>
        <label className="block text-gray-700 mb-1.5">이메일</label>
        <input
          type="email"
          className="w-full border border-gray-200 rounded-lg px-4 py-2 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 transition"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="your@email.com"
          required
        />
      </div>

      <div>
        <label className="block text-gray-700 mb-1.5">비밀번호</label>
        <input
          type="password"
          className="w-full border border-gray-200 rounded-lg px-4 py-2 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 transition"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="비밀번호"
          required
        />
      </div>

      {error && (
        <div className="bg-red-50 border border-red-300 text-red-600 text-sm rounded p-2 text-center mb-2">
          {error}
        </div>
      )}

      <button
        type="submit"
        className="w-full bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white font-bold py-2.5 rounded-lg shadow-md transition-all"
      >
        로그인
      </button>

      {/* 부가 링크(선택사항) */}
      {
      <div className="text-center text-sm text-gray-400 mt-4">
        계정이 없으신가요? <a href="/register" className="text-blue-700 font-semibold hover:underline">회원가입</a>
      </div>
      }
    </form>
  );
}
