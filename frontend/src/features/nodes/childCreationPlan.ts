import { v4 as uuid } from "uuid";
import { isProviderFailure } from "./createRequest";

type Payload = {
  content: string; parent_id: number; pos_x: number; pos_y: number;
  depth: number; order: number; state: string;
};

export type ChildCreationPlan = {
  prompt: string;
  children: { key: string; ai: boolean; done: boolean; payload: Payload }[];
};

export function childCreationPlan(prompt: string, aiCount: number, payloads: Payload[]): ChildCreationPlan {
  return {
    prompt,
    children: payloads.map((payload, index) => ({
      key: uuid(), ai: index < aiCount, done: false, payload: { ...payload },
    })),
  };
}

/** Retain both successful slots and uncertain request keys until the action completes. */
export async function runChildCreationPlan(
  plan: ChildCreationPlan,
  send: {
    ai: (prompt: string, payload: Payload, key: string) => Promise<unknown>;
    regular: (payload: Payload, key: string) => Promise<unknown>;
  },
  isCurrent: () => boolean = () => true,
): Promise<boolean> {
  for (let index = 0; index < plan.children.length; index++) {
    if (!isCurrent()) return false;
    const child = plan.children[index];
    if (child.done) continue;
    if (child.ai) {
      try {
        await send.ai(plan.prompt, child.payload, child.key);
        child.done = true;
        continue;
      } catch (error) {
        if (!isProviderFailure(error)) throw error;
        // A definitive provider failure permits the existing blank-node fallback.
        // Freeze that choice; a later retry must not create AI nodes in filled slots.
        for (const remaining of plan.children.slice(index)) {
          remaining.ai = false;
          remaining.key = uuid();
        }
      }
    }
    if (!isCurrent()) return false;
    await send.regular(child.payload, child.key);
    child.done = true;
  }
  return isCurrent();
}
