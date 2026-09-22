// features/auth/useAuth.ts
import { useRouter } from "next/navigation";
import { useState } from "react";
import { login, register } from "./authApi";
import { useQueryClient } from "@tanstack/react-query";
import axios from "axios";

export const useAuth = () => {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [error, setError] = useState("");

  const handleLogin = async (email: string, password: string) => {
    try {
      const { access_token } = await login(email, password);
      await queryClient.cancelQueries();
      queryClient.clear();
      localStorage.setItem("token", access_token);
      router.replace("/dashboard");
    } catch (error) {
      setError(axios.isAxiosError(error) && error.response?.status === 429
        ? "로그인 요청이 많습니다. 잠시 후 다시 시도해 주세요."
        : "이메일 또는 비밀번호가 올바르지 않습니다.");
    }
  };

  const handleRegister = async (email: string, password: string, name?: string) => {

    if (!email || !email.includes("@") || !password) {
    setError("이메일과 비밀번호를 올바르게 입력해주세요.");
    return;
  }

    try {
      await register(email, password, name);
      await handleLogin(email, password); // 자동 로그인
    } catch (error) {
      const status = axios.isAxiosError(error) ? error.response?.status : undefined;
      setError(status === 429 ? "가입 요청이 많습니다. 잠시 후 다시 시도해 주세요."
        : status === 422 ? "이름은 80자 이하, 비밀번호는 8자 이상·UTF-8 72바이트 이하로 입력해 주세요."
        : "회원가입에 실패했습니다. 이미 존재하는 계정일 수 있습니다.");
    }
  };

  return { handleLogin, handleRegister, error };
};
