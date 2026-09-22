import { test, expect } from "@playwright/test";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";

// Explicit, disposable-stack-only diagnostic. The whole scenario has a four-minute cap.
test("three tabs retain edits through offline and API restart", async ({ browser, request }, info) => {
  test.skip(process.env.PHASE3_STABILITY !== "1", "Explicit bounded fault diagnostic");
  test.setTimeout(240000);
  expect(process.env.PLAYWRIGHT_BASE_URL || "http://localhost:18080").toBe("http://localhost:18080");
  const token = process.env.JWT_TOKEN;
  if (!token) throw new Error("Disposable seed JWT_TOKEN required");
  const headers = { Authorization: `Bearer ${token}` };
  const started = Date.now();
  const projectResponse = await request.post("/projects", { headers, data: { name: "Bounded recovery diagnostic" } });
  expect(projectResponse.status()).toBe(201);
  const project = (await projectResponse.json()).id;
  const path = `/projects/${project}/nodes`;
  const root = (await (await request.get(path, { headers })).json())[0];
  expect((await request.patch(`${path}/${root.id}`, { headers, data: { expected_version: root.version, pos_x: 400, pos_y: 300 } })).status()).toBe(200);
  const context = await browser.newContext();
  await context.addInitScript(value => localStorage.setItem("token", value), token);
  const pages = await Promise.all([context.newPage(), context.newPage(), context.newPage()]);
  const errors: string[] = [];
  pages.forEach(page => page.on("pageerror", error => errors.push(error.message)));
  const sessions = await Promise.all(pages.map(page => context.newCDPSession(page)));
  await Promise.all(sessions.map(session => session.send("Performance.enable")));
  const heap = async () => Promise.all(sessions.map(async session => {
    await session.send("HeapProfiler.collectGarbage");
    const result = await session.send("Performance.getMetrics");
    return result.metrics.find(metric => metric.name === "JSHeapUsedSize")!.value;
  }));
  const compose = (...args: string[]) => promisify(execFile)("docker", ["compose", "-p", "brainnet-next-validation", "-f", "deploy/local-validation.compose.yml", ...args], { cwd: "..", timeout: 45000 });
  try {
    await Promise.all(pages.map(page => page.goto(`/dashboard/projects/${project}`)));
    const rootRows = pages.map(page => page.getByRole("list", { name: "그래프 노드" }).locator(`[data-node-id="${root.id}"]`));
    for (const row of rootRows) await expect(row).toHaveText(root.content);
    const beforeHeap = await heap();
    for (let round = 0; round < 12; round++) {
      const page = pages[round % 3];
      await page.bringToFront();
      await page.getByTestId("idea-graph").click({ position: { x: 400, y: 300 } });
      const content = `탭 ${round % 3 + 1} 저장 ${round + 1}`;
      await page.getByLabel("노드 내용", { exact: true }).fill(content);
      await page.getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
      for (const row of rootRows) await expect(row).toHaveText(content);
    }
    const current = (await (await request.get(path, { headers })).json())[0];
    const competing = await Promise.all(["동시 수정 A", "동시 수정 B"].map((content, index) => request.patch(`${path}/${root.id}`, {
      headers: { ...headers, "Idempotency-Key": `conflict-${project}-${index}` }, data: { content, expected_version: current.version }
    })));
    expect(competing.map(response => response.status()).sort()).toEqual([200, 409]);
    await context.setOffline(true);
    const data = { content: "연결 중단 중 서버 저장", parent_id: root.id, pos_x: 700, pos_y: 500 };
    const createHeaders = { ...headers, "Idempotency-Key": `restart-create-${project}` };
    const created = await request.post(path, { headers: createHeaders, data });
    expect(created.status()).toBe(201);
    const child = (await created.json())[0];
    await compose("restart", "fastapi", "fastapi-secondary");
    await expect.poll(async () => {
      try { return (await request.get("/health/events", { timeout: 3000 })).status(); } catch { return 0; }
    }, { timeout: 30000 }).toBe(200);
    const replay = await request.post(path, { headers: createHeaders, data });
    expect(replay.status()).toBe(201);
    expect((await replay.json())[0].id).toBe(child.id);
    await context.setOffline(false);
    for (const page of pages) await expect(page.getByRole("list", { name: "그래프 노드" }).locator(`[data-node-id="${child.id}"]`)).toHaveText(data.content, { timeout: 30000 });
    for (const page of pages) { await page.reload(); await expect(page.getByRole("list", { name: "그래프 노드" }).locator("li")).toHaveCount(2); }
    const persisted = await (await request.get(path, { headers })).json();
    expect(persisted).toHaveLength(2);
    expect(errors).toEqual([]);
    const afterHeap = await heap();
    const stats = await promisify(execFile)("docker", ["stats", "--no-stream", "--format", "{{json .}}", "brainnet-next-validation-fastapi-1", "brainnet-next-validation-fastapi-secondary-1"], { timeout: 15000 });
    const report = { elapsedSeconds: (Date.now() - started) / 1000, tabs: 3, uiEdits: 12, conflictStatuses: [200, 409], restartReplaySameId: true, nodeCount: persisted.length, pageErrors: errors, heapBeforeBytes: beforeHeap, heapAfterReloadBytes: afterHeap, dockerStats: stats.stdout.trim().split("\n").map(line => JSON.parse(line)), limitation: "Short recovery diagnostic; not long-term leak or load proof" };
    await fs.writeFile("../.tools/phase3-stability.json", JSON.stringify(report, null, 2));
    await pages[0].screenshot({ path: info.outputPath("restart-recovered.png"), fullPage: true });
    console.log(JSON.stringify(report));
  } finally {
    await context.close();
    await request.delete(`/projects/${project}`, { headers });
  }
});
