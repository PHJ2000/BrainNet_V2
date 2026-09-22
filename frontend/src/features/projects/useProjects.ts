import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {apiClient} from "@/lib/apiClient";
import type { Project } from "@/types/api";

export const useProjects = () => {
  return useQuery({
    queryKey: ["projects"],
    retry: false,
    queryFn: async ({ signal }) => {
      const res = await apiClient.get<Project[]>("/projects", { signal });
      return res.data;
    },
  });
};

export const useCreateProject = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ name, description }: { name: string; description?: string }) => {
      const res = await apiClient.post("/projects", { name, description });
      return res.data;
    },
    onSuccess: () => {
      // ✅ 캐시 무효화 → ProjectList가 자동 갱신됨
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
};
