import { test, expect } from "@playwright/test";

test("a delayed project response cannot replace the project selected afterward", async ({ page }) => {
  const projects = [{ id: 101, name: "Project A" }, { id: 202, name: "Project B" }];
  let releaseA!: () => void;
  const delayedA = new Promise<void>(resolve => { releaseA = resolve; });
  let requestedA!: () => void;
  const startedA = new Promise<void>(resolve => { requestedA = resolve; });
  let completedA!: () => void;
  const lateResponse = new Promise<void>(resolve => { completedA = resolve; });
  await page.addInitScript(() => localStorage.setItem("token", "navigation-test"));
  await page.route("**/*", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/projects") return route.fulfill({ json: projects });
    if (path === "/users/me") return route.fulfill({ json: { id: 1 } });
    if (path === "/projects/101") {
      requestedA();
      await delayedA;
      return route.fulfill({ json: projects[0] }).catch(() => undefined).finally(completedA);
    }
    if (path === "/projects/202") return route.fulfill({ json: projects[1] });
    if (path === "/projects/303") return route.fulfill({ status: 403, json: { message: "Forbidden" } });
    if (/^\/projects\/\d+\/tags$/.test(path)) return route.fulfill({ json: [] });
    if (/^\/projects\/\d+\/nodes$/.test(path)) return route.fulfill({ json: [{
      id: 2020, project_id: 202, content: "B root", state: "ACTIVE", depth: 0,
      order_index: 0, parent_id: null, pos_x: 400, pos_y: 300, tags: [], version: 0,
    }] });
    return route.continue();
  });
  try {
    await page.goto("/dashboard");
    await page.getByRole("link", { name: "Project A", exact: true }).first().click();
    await startedA;
    await page.getByRole("link", { name: "Project B", exact: true }).first().click();
    await expect(page.getByRole("heading", { name: "Project B", exact: true })).toBeVisible();
    releaseA();
    await lateResponse;
    await expect(page.getByRole("list", { name: "그래프 노드" })).toContainText("B root");
    await expect(page).toHaveURL(/\/projects\/202$/);
    await expect(page.getByRole("heading", { name: "Project A", exact: true })).toHaveCount(0);
    await page.goto("/dashboard/projects/303");
    await expect(page.getByRole("alert").filter({ hasText: "프로젝트를 불러올 수 없습니다" })).toBeVisible();
    await expect(page.getByTestId("idea-graph")).toHaveCount(0);
  } finally { releaseA(); }
});
