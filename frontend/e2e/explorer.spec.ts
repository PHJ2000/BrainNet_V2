import { test, expect } from "@playwright/test";
import os from "node:os";

test("search, OR tags, collapse, IME and remote tag events share one display model", async ({ browser, request }) => {
  const token = process.env.JWT_TOKEN!;
  const headers = { Authorization: `Bearer ${token}` };
  const p = await (await request.post("/projects", { headers, data: { name: "탐색 E2E" } })).json();
  const root = (await (await request.get(`/projects/${p.id}/nodes`, { headers })).json())[0];
  await request.patch(`/projects/${p.id}/nodes/${root.id}`, { headers, data: { content: "탐색 루트", expected_version: 0 } });
  const c = (await (await request.post(`/projects/${p.id}/nodes`, { headers, data: { content: "hello 가나다", parent_id: root.id, depth: 1, pos_x: 400, pos_y: 300 } })).json())[0];
  const g = (await (await request.post(`/projects/${p.id}/nodes`, { headers, data: { content: "deep HELLO", parent_id: c.id, depth: 2, pos_x: 700, pos_y: 550 } })).json())[0];
  const tag = await (await request.post(`/projects/${p.id}/tags`, { headers, data: { name: "검토" } })).json();
  await request.post(`/projects/${p.id}/tags/${tag.id}/nodes/${c.id}`, { headers });
  const contexts = await Promise.all([browser.newContext(), browser.newContext()]);
  await Promise.all(contexts.map(c => c.addInitScript(t => localStorage.setItem("token", t), token)));
  const pages = await Promise.all(contexts.map(c => c.newPage()));
  try {
    await Promise.all(pages.map(page => page.goto(`/dashboard/projects/${p.id}`)));
    const panel = pages[0].getByRole("complementary", { name: "노드 탐색" });
    const graph = pages[0].getByRole("list", { name: "그래프 노드" });
    await panel.getByRole("button", { name: "탐색 루트 접기", exact: true }).click();
    await expect(graph.locator("li")).toHaveCount(1);
    await pages[0].reload();
    await expect(graph.locator("li")).toHaveCount(1);
    const search = panel.getByRole("searchbox", { name: "노드 검색" });
    await search.fill(" hello ");
    await expect(panel.getByTestId("search-count")).toHaveText("검색 결과 2개");
    await expect(graph.locator("li")).toHaveCount(1);
    await panel.getByRole("button", { name: "deep HELLO", exact: true }).click();
    await expect(graph.locator("li")).toHaveCount(3);
    await search.fill("");
    await expect(graph.locator("li")).toHaveCount(1);
    await panel.getByRole("button", { name: "전체 해제" }).click();
    await expect(graph.locator("li")).toHaveCount(3);
    await search.dispatchEvent("compositionstart");
    await search.fill("가나다");
    await expect(panel.getByTestId("search-count")).toHaveText("전체 3개");
    await search.dispatchEvent("compositionend");
    await expect(panel.getByTestId("search-count")).toHaveText("검색 결과 1개");
    await search.fill("");
    for (const page of pages) {
      await page.getByRole("complementary", { name: "노드 탐색" }).getByRole("button", { name: "검토", exact: true }).click();
      await expect(page.getByTestId("search-count")).toHaveText("검색 결과 2개");
    }
    await request.delete(`/projects/${p.id}/tags/${tag.id}/nodes/${g.id}`, { headers });
    for (const page of pages) await expect(page.getByTestId("search-count")).toHaveText("검색 결과 1개");
    await request.patch(`/projects/${p.id}/tags/${tag.id}`, { headers, data: { name: "확인" } });
    for (const page of pages) await expect(page.getByRole("complementary", { name: "노드 탐색" }).getByRole("button", { name: "확인", exact: true })).toBeVisible();
    await search.focus(); await expect(search).toBeFocused();
    await search.fill("없는 내용");
    await expect(panel).toContainText("조건에 맞는 노드가 없어요.");
    expect((await (await request.get(`/projects/${p.id}/nodes`, { headers })).json()).length).toBe(3);
  } finally { await Promise.allSettled(contexts.map(c => c.close())); }
});

test("1000 nodes / depth 20 production browser display latency", async ({ page }, info) => {
  await page.addInitScript(t => localStorage.setItem("token", t), process.env.JWT_TOKEN!);
  const fixture = Array.from({ length: 1000 }, (_, i) => ({ id: 10000 + i, project_id: 1, author_id: 7,
    parent_id: i ? 10000 + (i % 20 === 0 ? 0 : i - 1) : null,
    content: i === 0 ? "성능 루트" : `찾기목표 ${i}`, state: "ACTIVE", depth: i % 20 + (i > 0 ? 1 : 0),
    order_index: i, pos_x: 400 + (i % 30) * 240, pos_y: 300 + Math.floor(i / 30) * 120, version: 0, tags: [] }));
  await page.route("**/projects/1/nodes", route => route.fulfill({ json: fixture }));
  const start = Date.now();
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1000개");
  const initialLoadMs = Date.now() - start;
  const search: number[] = [], collapse: number[] = [];
  for (let i = 0; i < 24; i++) {
    search.push(await page.evaluate(async ({ term, expected }) => {
      const input = document.querySelector<HTMLInputElement>("#node-search")!;
      const count = document.querySelector('[data-testid="search-count"]')!;
      return new Promise<number>(resolve => {
        const t = performance.now();
        const observer = new MutationObserver(() => {
          if (count.textContent !== expected) return;
          observer.disconnect(); requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now() - t)));
        });
        observer.observe(count, { subtree: true, childList: true, characterData: true });
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, term);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }, { term: i % 2 ? "없음" : "찾기목표", expected: `검색 결과 ${i % 2 ? 0 : 999}개` }));
  }
  await page.getByRole("button", { name: "전체 해제" }).click();
  for (let i = 0; i < 24; i++) {
    collapse.push(await page.evaluate(async () => {
      const button = document.querySelector<HTMLButtonElement>('[aria-label="성능 루트 접기"], [aria-label="성능 루트 펼치기"]')!;
      const before = button.getAttribute("aria-expanded");
      return new Promise<number>(resolve => {
        const t = performance.now();
        const observer = new MutationObserver(() => {
          if (button.getAttribute("aria-expanded") === before) return;
          observer.disconnect(); requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now() - t)));
        });
        observer.observe(button, { attributes: true }); button.click();
      });
    }));
  }
  const p95 = (values: number[]) => [...values].sort((a, b) => a - b)[Math.ceil(values.length * .95) - 1];
  const report = { build: "production", browser: page.context().browser()?.version(), cpu: os.cpus()[0].model,
    memoryGiB: Math.round(os.totalmem() / 2 ** 30), platform: os.platform(), nodes: 1000, depth: 20,
    initialLoadMs, search, collapse, searchP95Ms: p95(search), collapseP95Ms: p95(collapse) };
  await info.attach("display-performance", { body: JSON.stringify(report, null, 2), contentType: "application/json" });
  console.log(JSON.stringify(report));
  expect(report.searchP95Ms).toBeLessThan(300);
  expect(report.collapseP95Ms).toBeLessThan(200);
});
