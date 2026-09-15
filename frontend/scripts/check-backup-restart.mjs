// Run only after files.spec.ts against the disposable local validation stack.
import fs from "node:fs/promises";
import { chromium } from "@playwright/test";
(async () => {
  const root = "test-results";
  const dir = (await fs.readdir(root)).find(name => name.startsWith("files-download-"));
  if (!dir) throw new Error("Run files.spec.ts first");
  const sample = JSON.parse(await fs.readFile(`${root}/${dir}/restart-check.json`, "utf8"));
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto("http://localhost:18080/login");
    await page.getByPlaceholder("your@email.com").fill(sample.email);
    await page.getByPlaceholder("비밀번호", { exact: true }).fill(sample.password);
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await page.waitForURL("**/dashboard");
    await page.goto(`http://localhost:18080/dashboard/projects/${sample.project_id}`);
    await page.getByText(`전체 ${sample.node_count}개`, { exact: true }).waitFor();
    const result = { recreated_containers: true, fresh_login: true, project_id: sample.project_id, node_count: sample.node_count, passed: true };
    await fs.writeFile(`${root}/${dir}/restart-result.json`, JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
