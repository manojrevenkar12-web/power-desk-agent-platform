/** Typed client for the desk API. The token lives in memory and sessionStorage only. */

export type User = { id: string; name: string; role: string; desk: string };
export type Me = User & { books: string[]; tools: Record<"desk_agent" | "developer_tools", string[]>; skills: string[] };

export type NumberCheck = {
  text: string;
  value: number;
  unit: string | null;
  start: number;
  end: number;
  grounded: boolean;
  evidence: string | null;
  source: string | null;
  path: string | null;
  reason: string;
};

export type ToolCall = {
  name: string;
  input: Record<string, unknown>;
  ok: boolean;
  call_id: string;
  denied_by: string[];
  error: string | null;
  result: Record<string, unknown> | null;
};

export type Answer = {
  question: string;
  answer: string;
  skill: string | null;
  redacted: boolean;
  corrections: number;
  model_calls: number;
  ms: number;
  numbers: NumberCheck[];
  tool_calls: ToolCall[];
};

export type Interval = { at: string; da: number; solar_mw: number; wind_mw: number };
export type MarketDay = { zone: string; day: string; intervals: Interval[] };

export type SuiteSummary = {
  cases: number;
  passed: number;
  pass_rate: number;
  numbers_expected: number;
  numbers_correct: number;
  leaks: number;
  untraced_numbers_shipped: number;
  grounding_corrections: number;
  tool_calls_denied_by_policy: number;
  kb_filter_cedar_disagreements: number;
  failed: string[];
};
export type Evals = {
  dev?: { summary: SuiteSummary; cases_sha256: string; cases: { id: string; user: string; passed: boolean }[] };
  redteam?: { summary: SuiteSummary; cases_sha256: string; cases: { id: string; user: string; passed: boolean }[] };
  ablation?: { summary: SuiteSummary; cases_sha256: string; cases: { id: string; user: string; passed: boolean }[] };
  heldout: Record<string, { summary: SuiteSummary; cases_sha256: string; recorded_at: string; status: string }>;
};

export type Connector = {
  name: string;
  packages: string[];
  versions: Record<string, string>;
  distributions: number;
  size_mb: number;
  fits_lambda_zip: boolean;
  licences_flagged: { name: string; version: string; licence: string }[];
  import_ms_median_of_3: number;
  network_attempts_at_import: string[];
  mcp_tools_listed: number;
  mcp_call_ok: boolean;
  dev_surface_tools: number;
  dev_surface_book_tools: string[];
  anonymous: string;
  fit: boolean;
  install_error?: string;
};
export type ConnectorReport = { generated: string; python: string; expected_value: number; candidates: Connector[]; documented: Record<string, Record<string, string>> };

export type RolloutTeam = { description: string; managed_settings: Record<string, unknown>; managed_mcp: Record<string, unknown>; problems: string[] };
export type Rollout = { paths: Record<string, string>; teams: Record<string, RolloutTeam> };

export type AuditRow = { at: number; call_id: string; user: string; surface: string; tool: string; args_sha256: string; ok: boolean; error: string | null; denied_by: string[] };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "powerdesk.token";
let token: string | null = (() => {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
})();

export function setToken(t: string | null) {
  token = t;
  try {
    if (t) sessionStorage.setItem(TOKEN_KEY, t);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage can be unavailable; the in-memory token still works */
  }
}

export function hasToken() {
  return token !== null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = (await r.json()) as { detail?: string };
      detail = j.detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, detail);
  }
  return (await r.json()) as T;
}

export const api = {
  users: () => request<User[]>("/api/users"),
  login: (user: string) => request<{ token: string }>("/api/dev/login", { method: "POST", body: JSON.stringify({ user }) }),
  me: () => request<Me>("/api/me"),
  ask: (body: { question: string; surface?: string; attach_title?: string; attach_text?: string }) => request<Answer>("/api/ask", { method: "POST", body: JSON.stringify(body) }),
  marketDay: (zone: string, day: string) => request<MarketDay>(`/api/market/day?zone=${encodeURIComponent(zone)}&day=${encodeURIComponent(day)}`),
  evals: () => request<Evals>("/api/evals"),
  connectors: () => request<ConnectorReport>("/api/connectors"),
  rollout: () => request<Rollout>("/api/rollout"),
  audit: () => request<AuditRow[]>("/api/audit"),
};
