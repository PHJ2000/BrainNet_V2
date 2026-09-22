// lib/apiClient.ts
import axios from "axios";

export const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000",
  headers: {
    "Content-Type": "application/json",
  },
});

// 요청 시 JWT 자동 첨부
apiClient.interceptors.request.use((config) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(response => response, error => {
  if (typeof window !== "undefined" && axios.isAxiosError(error) &&
      error.response?.status === 401 && !error.config?.url?.startsWith("/auth/")) {
    const token = localStorage.getItem("token");
    // A delayed response from an older login must not invalidate a new session.
    if (token && error.config?.headers.Authorization === `Bearer ${token}`) {
      localStorage.removeItem("token");
      // Full navigation also discards all account-scoped caches and pending UI work.
      window.location.replace("/login?expired=1");
    }
  }
  return Promise.reject(error);
});
