import axios from "axios";
import { v4 as uuid } from "uuid";

export function isUncertainCreation(error: unknown): boolean {
  return !axios.isCancel(error) && axios.isAxiosError(error) && (!error.response ||
    (error.response.status === 409 && error.response.data?.code === "IDEMPOTENCY_IN_PROGRESS"));
}

export function isProviderFailure(error: unknown): boolean {
  return axios.isAxiosError(error) && !!error.response &&
    [502, 503, 504].includes(error.response.status) &&
    typeof error.response.data?.code === "string" && error.response.data.code.startsWith("AI_PROVIDER_");
}

function isCreationBusy(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 503 &&
    error.response.data?.code === "NODE_CREATION_BUSY";
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
      const busy = isCreationBusy(error);
      if (attempt >= 2 || (!busy && !isUncertainCreation(error))) throw error;
      // The admission gate returns Retry-After: 1 without claiming the key.
      await wait(busy ? 1000 : 250 * (attempt + 1));
    }
  }
}
