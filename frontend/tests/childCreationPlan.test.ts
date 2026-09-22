import test from "node:test";
import assert from "node:assert/strict";
import { AxiosError, AxiosHeaders } from "axios";
import { childCreationPlan, runChildCreationPlan } from "../src/features/nodes/childCreationPlan";

const payloads = [0, 1, 2].map((order) => ({
  content: "?", parent_id: 11, pos_x: order, pos_y: 0, depth: 1, order, state: "GHOST",
}));

test("navigation during provider failure does not create a fallback node", async () => {
  const plan = childCreationPlan("idea", 2, payloads);
  let current = true;
  let regularCalls = 0;
  const config = { headers: new AxiosHeaders() };
  const complete = await runChildCreationPlan(plan, {
    ai: async () => {
      current = false;
      throw new AxiosError("provider failed", undefined, config, undefined, {
        status: 503, statusText: "error", headers: {}, config, data: { code: "AI_PROVIDER_UNAVAILABLE" },
      });
    },
    regular: async () => { regularCalls++; },
  }, () => current);
  assert.equal(complete, false);
  assert.equal(regularCalls, 0);
});

test("partial success and lost response resume the original slots and keys", async () => {
  const plan = childCreationPlan("idea", 2, payloads);
  const attempts: string[] = [];
  let loseResponse = true;
  const sender = {
    ai: async (_prompt: string, _payload: unknown, key: string) => {
      attempts.push(key);
      if (loseResponse && attempts.length === 2) throw new AxiosError("response lost");
    },
    regular: async () => {},
  };
  await assert.rejects(runChildCreationPlan(plan, sender));
  assert.equal(plan.children[0].done, true);
  assert.equal(plan.children[1].ai, true);
  loseResponse = false;
  assert.equal(await runChildCreationPlan(plan, sender), true);
  assert.deepEqual(attempts, [plan.children[0].key, plan.children[1].key, plan.children[1].key]);
});

test("provider fallback stays fixed after a later blank-node failure", async () => {
  const plan = childCreationPlan("idea", 2, payloads);
  let aiCalls = 0;
  let blankCalls = 0;
  const config = { headers: new AxiosHeaders() };
  const sender = {
    ai: async () => {
      aiCalls++;
      throw new AxiosError("unconfigured", undefined, config, undefined, {
        status: 503, statusText: "unavailable", headers: {}, config,
        data: { code: "AI_PROVIDER_NOT_CONFIGURED" },
      });
    },
    regular: async () => {
      blankCalls++;
      if (blankCalls === 2) throw new AxiosError("lost blank response");
    },
  };
  await assert.rejects(runChildCreationPlan(plan, sender));
  assert.equal(await runChildCreationPlan(plan, sender), true);
  assert.equal(aiCalls, 1);
  assert.equal(blankCalls, 4);
  assert.equal(plan.children.every((child) => child.done), true);
});

test("project navigation stops further writes", async () => {
  const plan = childCreationPlan("idea", 2, payloads);
  let current = true;
  let calls = 0;
  const sender = { ai: async () => { calls++; current = false; }, regular: async () => { calls++; } };
  assert.equal(await runChildCreationPlan(plan, sender, () => current), false);
  assert.equal(calls, 1);
});
