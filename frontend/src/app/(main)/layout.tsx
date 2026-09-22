// app/(main)/layout.tsx
import Sidebar from "../components/Sidebar";
import AuthBoundary from "@/features/auth/AuthBoundary";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthBoundary>
      <div className="flex h-screen w-screen bg-gradient-to-br from-blue-50 via-white to-purple-100">
        {/* 사이드바 */}
        <aside className="relative z-10 w-[24%] min-w-[220px] max-w-[320px] border-r border-gray-200 bg-white/70 backdrop-blur-xl shadow-md flex flex-col">
          {/* 로고 + 앱 이름 */}
          <div className="px-6 py-7 border-b border-gray-100 flex flex-col items-center">
            <span className="text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-600 via-indigo-500 to-purple-600 tracking-wider select-none drop-shadow">
              BrainNet
            </span>
            <span className="text-gray-400 text-xs mt-1 mb-1">
              창의적인 아이디어를 정리하는 공간
            </span>
          </div>
          {/* 실제 네비게이션(프로젝트 등) */}
          <div className="flex-1 overflow-y-auto pt-2 pb-3">
            <Sidebar />
          </div>
        </aside>
        {/* 메인 콘텐츠 */}
        <main className="flex-1 flex flex-col h-full p-0 overflow-hidden">
          {/* 상단 헤더 (필요시) */}
          {/* 
          <header className="mb-8 flex items-center justify-between">
            <h1 className="text-2xl font-bold text-gray-800">프로젝트</h1>
            // 유저 프로필 등
          </header>
          */}
          {/* section → max-width/padding 제거 */}
          <section className="flex-1 w-full h-full">
            {children}
          </section>
        </main>
      </div>
    </AuthBoundary>
  );
}
