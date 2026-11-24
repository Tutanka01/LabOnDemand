import type { Probe, ProbeKind, ProbeVisibility } from "../../types/api";

/** Flat, string-based editing state for one probe (converted to/from the API `Probe`). */
export type ProbeFormState = {
  id: string;
  name: string;
  kind: ProbeKind;
  vantage: Probe["vantage"];
  visibility: ProbeVisibility;
  weight: number;
  // http
  url: string;
  method: string;
  expected_status: string;
  expected_body: string;
  // tcp
  tcp_host: string;
  tcp_port: string;
  // sql
  sql_query: string;
  sql_min_rows: string;
  // file
  file_path: string;
  file_contains: string;
  // command
  cmd: string;
  expected_exit: string;
};

export const PROBE_KINDS: ProbeKind[] = ["http", "tcp", "sql", "file", "command", "script"];

export const HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "HEAD"];

export const VISIBILITY_TONES: Record<ProbeVisibility, "green" | "amber" | "blue"> = {
  student: "green",
  summary: "amber",
  teacher_only: "blue",
};

export function emptyProbeForm(): ProbeFormState {
  return {
    id: "",
    name: "",
    kind: "http",
    vantage: "outside",
    visibility: "student",
    weight: 1,
    url: "",
    method: "GET",
    expected_status: "200",
    expected_body: "",
    tcp_host: "",
    tcp_port: "",
    sql_query: "",
    sql_min_rows: "1",
    file_path: "",
    file_contains: "",
    cmd: "",
    expected_exit: "0",
  };
}

export function probeFormToProbe(f: ProbeFormState): Probe {
  let config: Record<string, unknown> = {};
  let expect: Record<string, unknown> = {};
  switch (f.kind) {
    case "http":
      config = { url: f.url, method: f.method || "GET" };
      expect = {
        status: f.expected_status ? Number(f.expected_status) : 200,
        ...(f.expected_body ? { body_contains: f.expected_body } : {}),
      };
      break;
    case "tcp":
      config = { host: f.tcp_host, port: f.tcp_port ? Number(f.tcp_port) : 80 };
      expect = { open: true };
      break;
    case "sql":
      config = { query: f.sql_query };
      expect = { min_rows: f.sql_min_rows ? Number(f.sql_min_rows) : 1 };
      break;
    case "file":
      config = { path: f.file_path };
      expect = { exists: true, ...(f.file_contains ? { contains: f.file_contains } : {}) };
      break;
    case "command":
      config = { command: f.cmd };
      expect = { exit_code: f.expected_exit !== "" ? Number(f.expected_exit) : 0 };
      break;
    case "script":
      config = {};
      expect = {};
      break;
  }
  return {
    id: f.id || `probe-${Date.now()}`,
    name: f.name,
    kind: f.kind,
    vantage: f.vantage,
    visibility: f.visibility,
    weight: f.weight,
    config,
    expect,
  };
}

export function probeToFormState(p: Probe): ProbeFormState {
  const f = emptyProbeForm();
  f.id = p.id;
  f.name = p.name;
  f.kind = p.kind;
  f.vantage = p.vantage;
  f.visibility = p.visibility;
  f.weight = p.weight;
  const c = p.config as Record<string, unknown>;
  const e = p.expect as Record<string, unknown>;
  switch (p.kind) {
    case "http":
      f.url = (c.url as string) || "";
      f.method = (c.method as string) || "GET";
      f.expected_status = String(e.status ?? "200");
      f.expected_body = (e.body_contains as string) || "";
      break;
    case "tcp":
      f.tcp_host = (c.host as string) || "";
      f.tcp_port = String(c.port ?? "");
      break;
    case "sql":
      f.sql_query = (c.query as string) || "";
      f.sql_min_rows = String(e.min_rows ?? "1");
      break;
    case "file":
      f.file_path = (c.path as string) || "";
      f.file_contains = (e.contains as string) || "";
      break;
    case "command":
      f.cmd = (c.command as string) || "";
      f.expected_exit = String(e.exit_code ?? "0");
      break;
  }
  return f;
}
