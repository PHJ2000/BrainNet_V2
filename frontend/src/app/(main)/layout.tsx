import AuthBoundary from "@/features/auth/AuthBoundary";
import WorkspaceShell from "@/features/workspace/WorkspaceShell";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return <AuthBoundary><WorkspaceShell>{children}</WorkspaceShell></AuthBoundary>;
}
