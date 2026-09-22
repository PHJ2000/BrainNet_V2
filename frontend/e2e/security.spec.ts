import { expect, test } from "@playwright/test";

async function authenticatedGraph(page: import("@playwright/test").Page) {
  await page.addInitScript(() => localStorage.setItem("token", "test-session"));
  await page.route("**/*", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/users/me") return route.fulfill({ json: { id: 1 } });
    if (path === "/projects") return route.fulfill({ json: [{ id: 1, name: "Security test", owner_id: 1 }] });
    if (path === "/projects/1") return route.fulfill({ json: { id: 1, name: "Security test", owner_id: 1 } });
    if (path === "/projects/1/nodes") return route.fulfill({ json: [{ id: 1, project_id: 1,
      content: "Root", parent_id: null, state: "ACTIVE", depth: 0, order_index: 0,
      pos_x: 400, pos_y: 300, tags: [], version: 0 }] });
    if (path === "/projects/1/tags" || path === "/projects/1/operations") return route.fulfill({ json: [] });
    return route.continue();
  });
}

test("websocket expiry clears the current session and explains login expiry", async ({ page }, testInfo) => {
  await authenticatedGraph(page);
  let closeSocket!: () => void;
  await page.routeWebSocket(/\/projects\/1\/ws/, ws => { closeSocket = () => ws.close({ code: 4401 }); });
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("idea-graph")).toBeVisible();
  closeSocket();
  await expect(page).toHaveURL(/\/login\?expired=1$/);
  await expect(page.getByRole("status")).toContainText("로그인이 만료되었습니다");
  await page.screenshot({ path: testInfo.outputPath("session-expired.png") });
});

test("revoked project access hides the graph and heartbeat receives pong", async ({ page }, testInfo) => {
  await authenticatedGraph(page);
  let closeSocket!: () => void;
  let pong = false;
  await page.routeWebSocket(/\/projects\/1\/ws/, ws => {
    ws.onMessage(message => { if (message === "pong") pong = true; });
    ws.send(JSON.stringify({ type: "ping" }));
    closeSocket = () => ws.close({ code: 4403 });
  });
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("idea-graph")).toBeVisible();
  await expect.poll(() => pong).toBe(true);
  closeSocket();
  await expect(page.getByRole("alert").filter({ hasText: "프로젝트 접근 권한" })).toBeVisible();
  await expect(page.getByTestId("idea-graph")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("access-revoked.png") });
});
