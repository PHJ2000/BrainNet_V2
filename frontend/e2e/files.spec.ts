import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";

test("download original scope, preview backup, resume lost import after reload, and re-login", async ({ page, request }, info) => {
  const email = `backup-${Date.now()}@example.com`, password = "LocalBackupTest!42";
  expect((await request.post("/auth/register", { data: { email, password, name: "백업 검증" } })).status()).toBe(201);
  const auth = await request.post("/auth/login", { form: { username: email, password } });
  expect(auth.status()).toBe(200);
  const token = (await auth.json()).access_token;
  const headers = { Authorization: `Bearer ${token}`, "Idempotency-Key": "source-backup" };
  const content = "여러 줄 한글 😀\n<script>alert('never run')</script>\n```js\nconsole.log('original')\n```";
  const source = { schema_version: 1, exported_at: "2026-09-13T00:00:00Z", project: { name: "백업:검증?", description: "원본 내용 보존" },
    nodes: [
      { ref: "r", parent_ref: null, content: "원본 루트", state: "ACTIVE", depth: 0, order_index: 0, pos_x: 400, pos_y: 300 },
      { ref: "c", parent_ref: "r", content: "제안 내용", state: "GHOST", depth: 1, order_index: 0, pos_x: 650, pos_y: 400 },
      { ref: "g", parent_ref: "c", content, state: "ACTIVE", depth: 2, order_index: 0, pos_x: null, pos_y: null },
      { ref: "a", parent_ref: "r", content: "보관 내용", state: "ARCHIVED", depth: 1, order_index: 1, pos_x: 650, pos_y: 600 },
    ], tags: [{ ref: "t", name: "여행", color: "#6366f1" }], node_tags: [{ node_ref: "g", tag_ref: "t" }], depth_adjustments: [] };
  const seed = await request.post("/projects/import", { headers, data: source });
  expect(seed.status()).toBe(201);
  const pid = (await seed.json()).project_id;
  await page.goto("/login");
  await page.evaluate(t => localStorage.setItem("token", t), token);
  await page.goto(`/dashboard/projects/${pid}`);
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await expect(page.getByTestId("search-count")).toHaveText("전체 4개");
  await page.getByRole("searchbox", { name: "노드 검색" }).fill("검색 결과 없음");
  await expect(page.getByTestId("search-count")).toHaveText("검색 결과 0개");
  await page.getByRole("button", { name: "파일", exact: true }).click();
  const panel = page.getByRole("region", { name: "프로젝트 파일" });
  const mdEvent = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Markdown 저장" }).click();
  const md = await mdEvent;
  expect(md.suggestedFilename()).toBe("백업_검증_.md");
  const markdownPath = info.outputPath(md.suggestedFilename()); await md.saveAs(markdownPath);
  const markdown = await fs.readFile(markdownPath, "utf8");
  expect(markdown).toContain(content); expect(markdown).toContain("맥락 조상");
  expect(markdown).not.toContain("제안 내용"); expect(markdown).not.toContain("보관 내용");
  await panel.getByRole("checkbox", { name: "GHOST·ARCHIVED 포함" }).check();
  const allEvent = page.waitForEvent("download"); await panel.getByRole("button", { name: "Markdown 저장" }).click();
  const all = await allEvent; const allPath = info.outputPath("all-states.md"); await all.saveAs(allPath);
  expect(await fs.readFile(allPath, "utf8")).toContain("보관 내용");
  const jsonEvent = page.waitForEvent("download"); await panel.getByRole("button", { name: "전체 JSON 백업 저장" }).click();
  const json = await jsonEvent, jsonPath = info.outputPath("project-backup.json"); await json.saveAs(jsonPath);
  const exported = JSON.parse(await fs.readFile(jsonPath, "utf8"));
  expect(exported.nodes).toHaveLength(4); expect(JSON.stringify(exported)).not.toContain(email);
  await panel.getByRole("button", { name: "JSON 백업 가져오기" }).click();
  let dialog = page.getByRole("dialog", { name: "JSON 백업 복원" });
  await dialog.getByLabel("백업 JSON 파일").setInputFiles(jsonPath);
  await expect(dialog).toContainText("노드 4개 · 태그 1개 · 연결 1개");
  const keys: string[] = []; let restoredId = 0;
  await page.route("**/projects/import", async route => {
    keys.push(route.request().headers()["idempotency-key"]);
    const result = await route.fetch(); expect(result.status()).toBe(201);
    restoredId = (await result.json()).project_id;
    await route.abort("connectionreset");
  });
  await dialog.getByRole("button", { name: "새 프로젝트 생성 확인" }).click();
  await expect(dialog.getByRole("alert")).toContainText("같은 파일로 다시 시도");
  expect(keys).toHaveLength(3); expect(new Set(keys).size).toBe(1);
  await page.unroute("**/projects/import");
  await page.reload();
  await page.getByRole("button", { name: "파일", exact: true }).click();
  await panel.getByRole("button", { name: "JSON 백업 가져오기" }).click();
  dialog = page.getByRole("dialog", { name: "JSON 백업 복원" });
  await dialog.getByLabel("백업 JSON 파일").setInputFiles(jsonPath);
  await expect(dialog).toContainText("노드 4개");
  const replay = page.waitForRequest(r => r.url().endsWith("/projects/import"));
  await dialog.getByRole("button", { name: "새 프로젝트 생성 확인" }).click();
  expect((await replay).headers()["idempotency-key"]).toBe(keys[0]);
  await expect(page).toHaveURL(new RegExp(`/projects/${restoredId}$`));
  await expect(page.getByTestId("search-count")).toHaveText("전체 4개");
  expect((await (await request.get("/projects", { headers })).json()).length).toBe(2);
  const again = await (await request.get(`/projects/${restoredId}/export/json`, { headers })).json();
  delete again.exported_at; delete exported.exported_at;
  expect(again).toEqual(exported);
  await page.evaluate(() => localStorage.removeItem("token"));
  await page.goto("/login");
  await page.getByPlaceholder("your@email.com").fill(email); await page.getByPlaceholder("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto(`/dashboard/projects/${restoredId}`);
  await expect(page.getByTestId("search-count")).toHaveText("전체 4개");
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath("restored-project.png"), fullPage: true });
  // Disposable credentials remain only in ignored test artifacts for the restart verification.
  await fs.writeFile(info.outputPath("restart-check.json"), JSON.stringify({ email, password, project_id: restoredId, node_count: 4 }));
});
