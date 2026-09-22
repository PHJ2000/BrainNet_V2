import { test, expect } from "@playwright/test";

test("lost creation response, two browsers, mutation events and offline recovery", async ({ browser, request }, testInfo) => {
  const token = process.env.JWT_TOKEN;
  if (!token) throw new Error("JWT_TOKEN from the disposable contract seed is required");
  const contexts = await Promise.all([browser.newContext(), browser.newContext()]);
  await Promise.all(contexts.map((context) => context.addInitScript((value) => localStorage.setItem("token", value), token)));
  const pages = await Promise.all(contexts.map((context) => context.newPage()));
  const pageErrors: string[] = [];
  pages.forEach((page) => page.on("pageerror", (error) => pageErrors.push(error.message)));
  try {
    const keys: string[] = [];
    let dropped = false;
    await pages[0].route("**/projects/1/nodes", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      keys.push(route.request().headers()["idempotency-key"]);
      if (!dropped) {
        const committed = await route.fetch();
        expect(committed.status()).toBe(201);
        dropped = true;
        return route.abort("connectionreset");
      }
      return route.continue();
    });
    await Promise.all(pages.map((page) => page.goto("/dashboard/projects/1")));
    const lists = pages.map((page) => page.getByRole("list", { name: "그래프 노드" }));
    await Promise.all(lists.map((list) => expect(list.locator("li")).toHaveCount(3)));
    await pages[0].getByTestId("idea-graph").click({ position: { x: 400, y: 300 } });
    await pages[0].getByLabel("노드 내용", { exact: true }).fill("브라우저 재시도 검증");
    await pages[0].getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
    await expect(pages[0].getByRole("dialog")).toHaveCount(0);
    await pages[0].getByTestId("idea-graph").click({ button: "right", position: { x: 400, y: 300 } });
    await pages[0].getByText("AI 아이디어 생성", { exact: true }).click();
    await Promise.all(lists.map((list) => expect(list.locator("li")).toHaveCount(6, { timeout: 20000 })));
    expect(dropped).toBe(true);
    expect(keys).toHaveLength(4);
    expect(keys[0]).toBe(keys[1]);
    expect(new Set(keys).size).toBe(3);

    const headers = { Authorization: `Bearer ${token}`, "Idempotency-Key": "browser-remote-create" };
    const created = await request.post("/projects/1/nodes", { headers, data: { content: "다른 접속자의 노드", parent_id: 12, pos_x: 670, pos_y: 550 } });
    expect(created.status()).toBe(201);
    const node = (await created.json())[0];
    for (const list of lists) await expect(list.locator(`[data-node-id="${node.id}"]`)).toHaveText("다른 접속자의 노드");
    const updated = await request.patch(`/projects/1/nodes/${node.id}`, { headers: { ...headers, "Idempotency-Key": "browser-remote-edit" }, data: { content: "수정 이벤트 검증", expected_version: node.version } });
    expect(updated.status()).toBe(200);
    for (const list of lists) await expect(list.locator(`[data-node-id="${node.id}"]`)).toHaveText("수정 이벤트 검증");
    expect((await request.delete(`/projects/1/nodes/${node.id}`, { headers: { ...headers, "Idempotency-Key": "browser-remote-delete" } })).status()).toBe(204);
    for (const list of lists) await expect(list.locator(`[data-node-id="${node.id}"]`)).toHaveCount(0);

    await contexts[1].setOffline(true);
    const offline = await request.post("/projects/1/nodes", { headers: { ...headers, "Idempotency-Key": "browser-offline" }, data: { content: "재접속 복구 완료", parent_id: 12, pos_x: 680, pos_y: 570 } });
    expect(offline.status()).toBe(201);
    const offlineId = (await offline.json())[0].id;
    await contexts[1].setOffline(false);
    for (const list of lists) await expect(list.locator(`[data-node-id="${offlineId}"]`)).toHaveText("재접속 복구 완료", { timeout: 45000 });
    expect(pageErrors).toEqual([]);
    await pages[1].screenshot({ path: testInfo.outputPath("browser-verified.png"), fullPage: true });
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});
