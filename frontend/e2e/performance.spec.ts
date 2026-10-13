import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import os from "node:os";

for (const size of [1000, 5000]) test(`fixed ${size} node display measurement`, async ({ page }) => {
  test.skip(!process.env.PHASE2_PERF, "Run explicitly against a production build");
  const fixture = Array.from({ length: size }, (_, i) => ({ id: i + 1, project_id: 1,
    content: i ? `측정 목표 ${i}` : "측정 루트", parent_id: i ? (i % 20 === 0 ? 1 : i) : null,
    state: "ACTIVE", depth: i % 20, order_index: i, pos_x: 400 + i % 30 * 240,
    pos_y: 300 + Math.floor(i / 30) * 120, version: 0, tags: [] }));
  let nodeRequests = 0, tagRequests = 0;
  await page.addInitScript(() => localStorage.setItem("token", "perf-session"));
  await page.route("**/*", async route => {
    const path = new URL(route.request().url()).pathname;
    const project = { id: 1, name: "측정", owner_id: 1 };
    if (path === "/users/me") return route.fulfill({ json: { id: 1 } });
    if (path === "/projects") return route.fulfill({ json: [project] });
    if (path === "/projects/1") return route.fulfill({ json: project });
    if (path === "/projects/1/nodes") { nodeRequests++; return route.fulfill({ json: fixture }); }
    if (path === "/projects/1/tags") { tagRequests++; return route.fulfill({ json: [] }); }
    if (path === "/projects/1/operations") return route.fulfill({ json: [] });
    return route.continue();
  });
  await page.routeWebSocket(/\/projects\/1\/ws/, ws => ws.send(JSON.stringify({ type: "resync.required" })));
  const start = performance.now();
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText(`전체 ${size}개`);
  await expect(page.getByRole("list", { name: "그래프 노드" }).locator("li")).toHaveCount(size);
  const initialLoadMs = performance.now() - start;
  const samples: number[] = [];
  for (let i = 0; i < 14; i++) {
    samples.push(await page.evaluate(async ({ term, expected }) => {
      const input = document.querySelector<HTMLInputElement>("#node-search")!;
      const count = document.querySelector('[data-testid="search-count"]')!;
      return new Promise<number>(resolve => {
        const start = performance.now();
        const observer = new MutationObserver(() => {
          if (count.textContent !== expected) return;
          observer.disconnect(); requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now() - start)));
        });
        observer.observe(count, { subtree: true, childList: true, characterData: true });
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, term);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }, { term: i % 2 ? "없는본문" : "목표", expected: `검색 결과 ${i % 2 ? 0 : size - 1}개` }));
  }
  const sorted = samples.slice(2).sort((a, b) => a - b);
  const report = { size, initialLoadMs, searchP50Ms: sorted[Math.ceil(sorted.length * .5) - 1],
    searchP95Ms: sorted[Math.ceil(sorted.length * .95) - 1], samples, nodeRequests, tagRequests,
    responseBytes: Buffer.byteLength(JSON.stringify(fixture)), cpu: os.cpus()[0].model,
    browser: page.context().browser()?.version(), platform: os.platform() };
  await fs.mkdir("../.tools", { recursive: true });
  await fs.writeFile(`../.tools/perf-${process.env.PHASE2_PERF}-${size}.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
});
