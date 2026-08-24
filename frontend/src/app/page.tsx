"use client";

import Link from "next/link";

export default function HomePage() {
  return (
    <main className="min-h-screen flex flex-col bg-gradient-to-r from-gray-100 to-blue-100 items-center justify-center px-4 space-y-40 overflow-hidden bg-red">

      <div className="w-full flex justify-center z-10 ">
        <h1
          className="text-8xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-600 via-indigo-500 to-purple-600 drop-shadow tracking-widest inline-block text-center"
          style={{ letterSpacing: "0.25em" }}
        >
          Brain Net
        </h1>
      </div>

      <div className="w-full max-w-md bg-white p-8 rounded-xl shadow-md space-y-6 z-10">
        <div className="space-y-4">
          <Link
            href="/login"
            className="block w-full text-center bg-gradient-to-r from-green-500 to-blue-500 hover:from-green-600 hover:to-blue-600 text-white font-bold py-2.5 rounded-lg shadow-md transition-all"
          >
            로그인
          </Link>
          <Link
            href="/register"
            className="block w-full text-center bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white font-bold py-2.5 rounded-lg shadow-md transition-all"
          >
            회원가입
          </Link>
        </div>
        <p className="text-center text-sm text-gray-400 mt-4">
          실시간 브레인스토밍 협업 플랫폼
        </p>
      </div>
    </main>
  );
}
