import { request, type FullConfig } from "@playwright/test";

/** Dedicated disposable account; never depend on a developer's login or project IDs. */
export default async function setup(config: FullConfig) {
  if (process.env.JWT_TOKEN) return;
  const api = await request.newContext({ baseURL: config.projects[0].use.baseURL });
  try {
    const email = `browser-suite-${crypto.randomUUID()}@example.com`;
    const password = "BrowserSuiteVerification!42";
    const created = await api.post("/auth/register", { data: { email, password, name: "Browser suite" } });
    if (created.status() !== 201) throw new Error(`Test registration failed: ${created.status()}`);
    const login = await api.post("/auth/login", { form: { username: email, password } });
    if (!login.ok()) throw new Error(`Test login failed: ${login.status()}`);
    process.env.JWT_TOKEN = (await login.json()).access_token;
  } finally { await api.dispose(); }
}
