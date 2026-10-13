import test from "node:test";
import assert from "node:assert/strict";
import { AxiosError, AxiosHeaders, CanceledError } from "axios";
import { createRequest, isProviderFailure } from "../src/features/nodes/createRequest";

const noWait = async () => {};

test("cancelled navigation requests are never retried", async () => {
  let calls = 0;
  await assert.rejects(createRequest(async () => {
    calls++; throw new CanceledError("unmounted");
  }, "cancelled", noWait));
  assert.equal(calls, 1);
});

test("lost response retries the same operation key", async () => {
  const keys: string[] = [];
  const result = await createRequest(async (key) => {
    keys.push(key);
    if (keys.length === 1) throw new AxiosError("connection lost");
    return { id: 12 };
  }, "same-operation", noWait);
  assert.deepEqual(keys, ["same-operation", "same-operation"]);
  assert.equal(result.id, 12);
});

test("independent operations receive different keys", async () => {
  const first = await createRequest(async (key) => key);
  const second = await createRequest(async (key) => key);
  assert.notEqual(first, second);
});

function responseError(status: number, code: string) {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("request failed", undefined, config, undefined, {
    status, statusText: "error", headers: {}, config, data: { code },
  });
}

test("in-progress claim retries but key reuse and provider errors do not", async () => {
  for (const [status, code, expected] of [
    [409, "IDEMPOTENCY_IN_PROGRESS", 3],
    [409, "IDEMPOTENCY_KEY_REUSED", 1],
    [502, "AI_PROVIDER_UNAVAILABLE", 1],
    [503, "NODE_CREATION_BUSY", 3],
    [401, "UNAUTHORIZED", 1],
  ] as const) {
    let calls = 0;
    await assert.rejects(createRequest(async () => {
      calls++;
      throw responseError(status, code);
    }, "key", noWait));
    assert.equal(calls, expected);
  }
});

test("busy admission retains its key and waits before retry without AI fallback", async () => {
  const keys: string[] = [];
  const waits: number[] = [];
  const busy = responseError(503, "NODE_CREATION_BUSY");
  assert.equal(isProviderFailure(busy), false);
  const value = await createRequest(async (key) => {
    keys.push(key);
    if (keys.length === 1) throw busy;
    return 12;
  }, "queued-operation", async (ms) => { waits.push(ms); });
  assert.equal(value, 12);
  assert.deepEqual(keys, ["queued-operation", "queued-operation"]);
  assert.deepEqual(waits, [1000]);
});

test("transport retry is bounded and preserves caller key for a later retry", async () => {
  let calls = 0;
  await assert.rejects(createRequest(async () => {
    calls++;
    throw new AxiosError("offline");
  }, "persisted-operation", noWait));
  assert.equal(calls, 3);
  assert.equal(await createRequest(async (key) => key, "persisted-operation"), "persisted-operation");
});
