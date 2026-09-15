import { test, expect } from "@playwright/test";

test("history undo survives a lost response and deleted branches recover in two browsers", async ({ browser, request }, testInfo) => {
  const token = process.env.JWT_TOKEN;
  if (!token) throw new Error("Dedicated test token required");
  const headers = { Authorization: `Bearer ${token}` };
  const projectResponse = await request.post("/projects", { headers, data: { name: "변경 기록 E2E" } });
  expect(projectResponse.status()).toBe(201);
  const project = (await projectResponse.json()).id;
  const root = (await (await request.get(`/projects/${project}/nodes`, { headers })).json())[0];
  const created = await request.post(`/projects/${project}/nodes`, { headers: { ...headers, "Idempotency-Key": "history-child" },
    data: { content: "복구할 자식", parent_id: root.id, pos_x: 400, pos_y: 300 } });
  expect(created.status()).toBe(201);
  const child = (await created.json())[0];
  const edit = await request.patch(`/projects/${project}/nodes/${child.id}`, { headers: { ...headers, "Idempotency-Key": "history-move" },
    data: { content: "수정된 자식", pos_x: 430, pos_y: 350, expected_version: child.version } });
  expect(edit.status()).toBe(200);
  const contexts = await Promise.all([browser.newContext(), browser.newContext()]);
  await Promise.all(contexts.map(c => c.addInitScript(t => localStorage.setItem("token", t), token)));
  const pages = await Promise.all(contexts.map(c => c.newPage()));
  const errors: string[] = [];
  pages.forEach(p => p.on("pageerror", e => errors.push(e.message)));
  try {
    await Promise.all(pages.map(p => p.goto(`/dashboard/projects/${project}`)));
    const lists = pages.map(p => p.getByRole("list", { name: "그래프 노드" }));
    for (const list of lists) await expect(list).toContainText("수정된 자식");
    await pages[0].getByRole("button", { name: "변경 기록", exact: true }).click();
    const history = pages[0].getByRole("complementary", { name: "노드 변경 기록" });
    await history.getByRole("button", { name: "되돌리기 미리보기" }).first().click();
    const dialog = pages[0].getByRole("dialog", { name: "실행 취소 미리보기" });
    await expect(dialog).toContainText("수정된 자식");
    await expect(dialog).toContainText("복구할 자식");
    const keys: string[] = [];
    let dropped = false;
    await pages[0].route("**/operations/*/undo", async route => {
      keys.push(route.request().headers()["idempotency-key"]);
      if (!dropped) {
        const committed = await route.fetch();
        expect(committed.status()).toBe(200);
        dropped = true;
        return route.abort("connectionreset");
      }
      return route.continue();
    });
    await dialog.getByRole("button", { name: "실행 취소 확인" }).click();
    await expect(dialog).toHaveCount(0);
    expect(keys).toHaveLength(2); expect(keys[0]).toBe(keys[1]);
    for (const list of lists) await expect(list).toContainText("복구할 자식");

    // Use the actual context-menu preview and deletion, not an API-only substitute.
    await pages[0].getByRole("button", { name: "변경 기록", exact: true }).click();
    await pages[0].getByTestId("idea-graph").click({ button: "right", position: { x: 400, y: 300 } });
    await pages[0].getByText("가지 삭제…", { exact: true }).click();
    const deletion = pages[0].getByRole("dialog", { name: "가지 삭제 미리보기" });
    await expect(deletion).toContainText("복구할 자식");
    await deletion.getByRole("button", { name: "가지 삭제 확인" }).click();
    await expect(deletion).toHaveCount(0);
    for (const list of lists) await expect(list.locator(`[data-node-id="${child.id}"]`)).toHaveCount(0);
    await pages[0].reload();
    await pages[0].getByRole("button", { name: "변경 기록", exact: true }).click();
    await history.getByRole("button", { name: "되돌리기 미리보기" }).first().click();
    await dialog.getByRole("button", { name: "실행 취소 확인" }).click();
    for (const list of lists) await expect(list.locator(`[data-node-id="${child.id}"]`)).toHaveText("복구할 자식");
    await contexts[1].setOffline(true); await contexts[1].setOffline(false); await pages[1].reload();
    await expect(lists[1]).toContainText("복구할 자식");
    expect(errors).toEqual([]);
    await pages[0].screenshot({ path: testInfo.outputPath("history-recovery.png"), fullPage: true });
  } finally {
    await Promise.allSettled(contexts.map(c => c.close()));
  }
});
