import axios from "axios";
import { v4 as uuid } from "uuid";

export function isUncertainCreation(error: unknown): boolean {
  return axios.isAxiosError(error) && (!error.response ||
    (error.response.status === 409 && error.response.data?.code === "IDEMPOTENCY_IN_PROGRESS"));
}

export function isProviderFailure(error: unknown): boolean {
  return axios.isAxiosError(error) && !!error.response &&
    [502, 503, 504].includes(error.response.status) &&
    typeof error.response.data?.code === "string" && error.response.data.code.startsWith("AI_PROVIDER_");
}

/** One user operation keeps its key across transport retries. */
export async function createRequest<T>(
  send: (key: string) => Promise<T>,
  key = uuid(),
  wait: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await send(key);
    } catch (error) {
      if (attempt >= 2 || !isUncertainCreation(error)) throw error;
      await wait(250 * (attempt + 1));
    }
  }
}
