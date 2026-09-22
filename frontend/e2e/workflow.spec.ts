import { test, expect, type Page, type WebSocketRoute } from "@playwright/test";

async function fixture(page: Page) {
  const state = { userId: 1, readOnly: false, tagFail: false, tagAttached: false, aiEnabled: false, aiFail: false, projectFail: false, nodeFail: false, detailFail: false, writeMode: "ok", writes: [] as string[],
    reads: 0, nodeWrites: [] as string[], createFail: false, socket: null as WebSocketRoute | null, connections: 0,
    nodes: [{ id: 1, project_id: 1, content: "원본", parent_id: null as number | null, state: "ACTIVE", depth: 0,
      order_index: 0, pos_x: 400, pos_y: 300, tags: [], version: 0 }] };
  const projects = [{ id: 1, name: "가나다", owner_id: 1, created_at: "2026-01-01T00:00:00Z" },
    { id: 2, name: "라마바", owner_id: 1, created_at: "2026-09-01T00:00:00Z" }];
  await page.addInitScript(() => localStorage.setItem("token", "workflow-session"));
  await page.route("**/*", async route => {
    const path = new URL(route.request().url()).pathname, method = route.request().method();
    const fail = (status = 503, code = "UNAVAILABLE") => route.fulfill({ status, json: { code, message: "fixture" } });
    if (path === "/users/me") return route.fulfill({ json: { id: state.userId } });
    if (path === "/projects") return state.projectFail ? fail() : route.fulfill({ json: projects });
    if (path === "/projects/1") return state.detailFail ? fail() : route.fulfill({ json: { ...projects[0], my_role: state.readOnly ? "VIEWER" : "OWNER", ai_enabled: state.aiEnabled } });
    if (path === "/projects/2") return route.fulfill({ json: projects[1] });
    if (path === "/projects/2/nodes") return route.fulfill({ json: [{ ...state.nodes[0], id: 22, project_id: 2, content: "다른 프로젝트" }] });
    if (path === "/projects/2/tags") return route.fulfill({ json: [] });
    if (path === "/projects/1/nodes/1" && method === "PATCH") {
      state.writes.push(route.request().headers()["idempotency-key"]);
      if (state.writeMode === "fail") return fail();
      if (state.writeMode === "conflict") return fail(409, "NODE_VERSION_CONFLICT");
      state.nodes[0] = { ...state.nodes[0], ...route.request().postDataJSON(), version: state.nodes[0].version + 1 };
      return route.fulfill({ json: state.nodes[0] });
    }
    if (path === "/projects/1/tags/5/nodes/1") {
      if (state.tagFail) return fail();
      state.tagAttached = method === "POST"; return route.fulfill({ json: { status: "ok" } });
    }
    if (path === "/projects/1/nodes") {
      if (method === "POST") {
        state.nodeWrites.push(route.request().headers()["idempotency-key"]);
        if (state.aiFail && route.request().postDataJSON().ai_prompt) return fail(503, "AI_PROVIDER_NOT_CONFIGURED");
        if (state.createFail) return fail();
        const node = { ...state.nodes[0], ...route.request().postDataJSON(), id: state.nodes.length + 1 };
        state.nodes.push(node);
        return route.fulfill({ status: 201, json: [node] });
      }
      state.reads++;
      return state.nodeFail ? fail() : route.fulfill({ json: state.nodes.map(n => ({ ...n, tags: state.tagAttached ? [5] : [] })) });
    }
    if (path === "/projects/1/tags") return route.fulfill({ json: [{ id: 5, name: "검토", node_count: 0 }] });
    if (path === "/projects/1/operations") return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.continue();
  });
  await page.routeWebSocket(/\/projects\/[12]\/ws/, ws => {
    state.socket = ws; state.connections++;
    ws.send(JSON.stringify({ type: "resync.required" }));
  });
  return state;
}

test("project errors recover into searchable sorted results and distinct empty search", async ({ page }) => {
  const state = await fixture(page); state.projectFail = true;
  await page.goto("/dashboard");
  await expect(page.getByText("생성된 프로젝트가 없습니다.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "프로젝트 다시 불러오기" })).toBeVisible();
  state.projectFail = false;
  await page.getByRole("button", { name: "프로젝트 다시 불러오기" }).click();
  const list = page.getByRole("region", { name: "프로젝트 목록" });
  await expect(list.getByRole("link").first()).toContainText("라마바");
  await page.getByLabel("프로젝트 정렬").selectOption("name");
  await expect(list.getByRole("link").first()).toContainText("가나다");
  await page.getByRole("searchbox", { name: "프로젝트 이름 검색" }).fill("가나다".normalize("NFD"));
  await expect(list.getByRole("link")).toHaveCount(1);
  await page.getByRole("searchbox", { name: "프로젝트 이름 검색" }).fill("없는프로젝트");
  await expect(list).toContainText("검색 조건에 맞는 프로젝트가 없습니다.");
});

test("server outage is not a deleted project and graph load offers retry", async ({ page }) => {
  const state = await fixture(page); state.detailFail = true;
  await page.goto("/dashboard/projects/1");
  await expect(page.getByText("요청을 처리하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.")).toBeVisible();
  await expect(page.getByText("프로젝트 또는 초대 코드를 찾을 수 없습니다.")).toHaveCount(0);
  state.detailFail = false; state.nodeFail = true;
  await page.getByRole("button", { name: "다시 시도", exact: true }).click();
  await expect(page.getByRole("button", { name: "노드 다시 불러오기" })).toBeVisible();
  state.nodeFail = false;
  await page.getByRole("button", { name: "노드 다시 불러오기" }).click();
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await expect(page.getByRole("button", { name: "노드 다시 불러오기" })).toHaveCount(0);
});

test("failed node edit retains draft and manual retry reuses the operation key", async ({ page }, info) => {
  const state = await fixture(page); state.writeMode = "fail";
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await page.getByTestId("idea-graph").click({ position: { x: 400, y: 300 } });
  await page.getByLabel("노드 내용", { exact: true }).fill("보존할 입력");
  await page.getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
  const status = page.getByLabel("동기화 상태");
  await expect(status).toContainText("보존할 입력");
  await expect(status).toContainText("저장하지 못했습니다");
  await page.screenshot({ path: info.outputPath("save-retry.png") });
  state.writeMode = "ok";
  await page.getByRole("dialog").getByRole("button", { name: "저장 다시 시도" }).click();
  await expect(status).toContainText("저장 완료");
  expect(state.writes).toHaveLength(2);
  expect(new Set(state.writes).size).toBe(1);
  await expect(page.getByRole("list", { name: "그래프 노드" }).locator('[data-node-id="1"]')).toHaveText("보존할 입력");
});

test("conflict retains input and reading current state does not retry a write", async ({ page }) => {
  const state = await fixture(page); state.writeMode = "conflict";
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await page.getByTestId("idea-graph").click({ position: { x: 400, y: 300 } });
  await page.getByLabel("노드 내용", { exact: true }).fill("충돌 입력");
  await page.getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByLabel("동기화 상태")).toContainText("다른 변경과 충돌");
  await expect(page.getByRole("button", { name: "저장 다시 시도" })).toHaveCount(0);
  const before = state.reads;
  await page.getByRole("dialog").getByRole("button", { name: "최신 상태 확인" }).click();
  await expect.poll(() => state.reads).toBeGreaterThan(before);
  expect(state.writes).toHaveLength(1);
  await expect(page.getByLabel("동기화 상태")).toContainText("충돌 입력");
});

test("failed child creation keeps its key when the user retries", async ({ page }) => {
  const state = await fixture(page); state.createFail = true;
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await page.getByTestId("idea-graph").click({ button: "right", position: { x: 400, y: 300 } });
  await page.getByText("자식 노드 추가…", { exact: true }).click();
  await page.getByLabel("노드 내용", { exact: true }).fill("추가할 노드");
  await page.getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByLabel("동기화 상태")).toContainText("저장하지 못했습니다");
  state.createFail = false;
  await page.getByRole("dialog").getByRole("button", { name: "저장 다시 시도" }).click();
  await expect(page.getByTestId("search-count")).toHaveText("전체 2개");
  expect(state.nodeWrites).toHaveLength(2);
  expect(new Set(state.nodeWrites).size).toBe(1);
});

test("reconnecting announces its state and resyncs after the connection returns", async ({ page }) => {
  const state = await fixture(page);
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  const before = state.reads;
  state.socket!.close({ code: 1012 });
  await expect(page.getByLabel("동기화 상태")).toContainText("재연결 중");
  await expect.poll(() => state.connections).toBe(2);
  await expect(page.getByLabel("동기화 상태")).toContainText("연결됨");
  await expect.poll(() => state.reads).toBeGreaterThan(before);
});

test("a failed draft cannot be retried in the next project", async ({ page }) => {
  const state = await fixture(page); state.writeMode = "fail";
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await page.getByTestId("idea-graph").click({ position: { x: 400, y: 300 } });
  await page.getByLabel("노드 내용", { exact: true }).fill("이전 프로젝트 입력");
  await page.getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByLabel("동기화 상태")).toContainText("저장하지 못했습니다");
  await page.getByRole("dialog").getByRole("button", { name: "닫기", exact: true }).click();
  await page.getByRole("link", { name: "라마바", exact: true }).click();
  await expect(page.getByRole("list", { name: "그래프 노드" })).toContainText("다른 프로젝트");
  await expect(page.getByLabel("동기화 상태")).toContainText("변경 없음");
  await expect(page.getByRole("button", { name: "저장 다시 시도" })).toHaveCount(0);
  expect(state.writes).toHaveLength(1);
});

test("editor restores a failed draft and operation key after reload", async ({ page }, info) => {
  const state = await fixture(page); state.writeMode = "fail";
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await page.getByTestId("idea-graph").click({ position: { x: 400, y: 300 } });
  await page.getByLabel("노드 내용", { exact: true }).fill("새로고침 후에도 보존\n두 번째 줄");
  await page.getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  await page.reload();
  await page.getByRole("button", { name: "초안 이어쓰기" }).click();
  await expect(page.getByLabel("노드 내용", { exact: true })).toHaveValue("새로고침 후에도 보존\n두 번째 줄");
  await page.screenshot({ path: info.outputPath("restored-draft.png") });
  state.writeMode = "ok";
  await page.getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(state.writes).toHaveLength(2); expect(new Set(state.writes).size).toBe(1);
  expect(state.nodeWrites).toHaveLength(0); // Manual saving never invokes AI/child creation.
  await page.reload();
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await expect(page.getByRole("button", { name: "초안 이어쓰기" })).toHaveCount(0);
});

test("drafts are separated by account and viewer cannot open a writer", async ({ page }) => {
  const state = await fixture(page);
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await page.getByTestId("idea-graph").click({ position: { x: 400, y: 300 } });
  await page.getByLabel("노드 내용", { exact: true }).fill("첫 계정 초안");
  state.userId = 2; state.readOnly = true;
  await page.reload();
  await expect(page.getByLabel("동기화 상태")).toContainText("읽기 전용");
  await expect(page.getByRole("button", { name: "초안 이어쓰기" })).toHaveCount(0);
  await page.getByTestId("idea-graph").click({ position: { x: 400, y: 300 } });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(state.writes).toHaveLength(0);
});

test("tag failures are visible and retry reconciles server state", async ({ page }) => {
  const state = await fixture(page); state.tagFail = true;
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await page.getByTestId("idea-graph").click({ button: "right", position: { x: 400, y: 300 } });
  await page.getByText("태그 달기…", { exact: true }).hover();
  await page.getByRole("menuitem", { name: "검토", exact: true }).click();
  await expect(page.getByRole("button", { name: "태그 다시 시도" })).toBeVisible();
  state.tagFail = false;
  await page.getByRole("button", { name: "태그 다시 시도" }).click();
  await expect.poll(() => state.tagAttached).toBe(true);
  await expect(page.getByRole("status").filter({ hasText: "태그 · 저장 완료" })).toBeVisible();
});

test("AI failure is an explicit action and never replaces manual content", async ({ page }) => {
  const state = await fixture(page); state.aiEnabled = true; state.aiFail = true;
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  await page.getByTestId("idea-graph").click({ button: "right", position: { x: 400, y: 300 } });
  await page.getByText("AI 아이디어 생성", { exact: true }).click();
  await expect(page.getByLabel("동기화 상태")).toContainText("저장하지 못했습니다");
  await expect(page.getByRole("list", { name: "그래프 노드" })).toContainText("원본");
  expect(state.nodes).toHaveLength(1); expect(state.writes).toHaveLength(0);
});

test("owner changes member role removes member and revokes invitation", async ({ page }, info) => {
  await fixture(page);
  let members = [{ user_id: 1, email: "owner@example.test", role: "OWNER" }, { user_id: 2, email: "reader@example.test", role: "EDITOR" }];
  let invitations = [{ email: "pending@example.test", role: "VIEWER", expires_at: "2026-10-01" }];
  await page.route("**/projects/1/members**", route => {
    if (route.request().method() === "PATCH") { members[1].role = route.request().postDataJSON().role; return route.fulfill({ json: members[1] }); }
    if (route.request().method() === "DELETE") { members = members.slice(0, 1); return route.fulfill({ status: 204 }); }
    return route.fulfill({ json: members });
  });
  await page.route("**/projects/1/invitations**", route => {
    if (route.request().method() === "DELETE") { invitations = []; return route.fulfill({ status: 204 }); }
    return route.fulfill({ json: invitations });
  });
  await page.goto("/dashboard/projects/1");
  await page.getByRole("button", { name: "멤버 관리" }).click();
  const dialog = page.getByRole("dialog", { name: "프로젝트 멤버" });
  await dialog.getByLabel("reader@example.test 권한").selectOption("VIEWER");
  await expect(dialog.getByLabel("reader@example.test 권한")).toHaveValue("VIEWER");
  await page.screenshot({ path: info.outputPath("members.png") });
  await dialog.getByRole("button", { name: "내보내기", exact: true }).click();
  await dialog.getByRole("button", { name: "내보내기 확인" }).click();
  await expect(dialog).not.toContainText("reader@example.test");
  await dialog.getByRole("button", { name: "초대 철회" }).click();
  await expect(dialog).toContainText("대기 중인 초대가 없습니다.");
});

test("unchanged graph resync reuses snapshot and skips tag download", async ({ page }) => {
  const state = await fixture(page);
  let requests = 0, tagReads = 0;
  page.on("request", request => { if (new URL(request.url()).pathname === "/projects/1/tags") tagReads++; });
  await page.route("**/projects/1/nodes", route => {
    requests++;
    if (route.request().headers()["if-none-match"] === '"same"') return route.fulfill({ status: 304, headers: { ETag: '"same"' } });
    return route.fulfill({ json: state.nodes, headers: { ETag: '"same"' } });
  });
  await page.goto("/dashboard/projects/1");
  await expect(page.getByTestId("search-count")).toHaveText("전체 1개");
  state.socket!.send(JSON.stringify({ type: "resync.required" }));
  await expect.poll(() => requests).toBe(2);
  expect(tagReads).toBe(1);
  await expect(page.getByRole("list", { name: "그래프 노드" })).toContainText("원본");
});
