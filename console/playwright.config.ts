import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:8799" },
  webServer: {
    command: "npx vite build && cd .. && POWERDESK_DEV_SECRET=e2e-dev-secret-0123456789abcdefghijklmn ${PYTHON:-.venv/bin/python} -m uvicorn powerdesk.api:app --port 8799",
    url: "http://127.0.0.1:8799/api/health",
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
