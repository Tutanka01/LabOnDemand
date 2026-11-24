import type { ReactNode } from "react";
import { useI18n } from "../../lib/i18n";
import { HTTP_METHODS, type ProbeFormState } from "./probeForm";

function Field({ id, label, full, children }: { id: string; label: string; full?: boolean; children: ReactNode }) {
  return (
    <div className={full ? "field full" : "field"}>
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}

/** Kind-specific inputs of the probe form (URL for HTTP, host/port for TCP, ...). */
export function ProbeConfigFields({
  form,
  setForm,
}: {
  form: ProbeFormState;
  setForm: (f: ProbeFormState) => void;
}) {
  const { t } = useI18n();
  const set = (key: keyof ProbeFormState, val: string | number) => setForm({ ...form, [key]: val });

  switch (form.kind) {
    case "http":
      return (
        <>
          <Field id="probe-url" label={t("probe.field_url")} full>
            <input
              id="probe-url"
              placeholder="http://lab-url/health"
              value={form.url}
              onChange={(e) => set("url", e.target.value)}
            />
          </Field>
          <Field id="probe-method" label={t("probe.field_method")}>
            <select id="probe-method" value={form.method} onChange={(e) => set("method", e.target.value)}>
              {HTTP_METHODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
          <Field id="probe-status" label={t("probe.field_expected_status")}>
            <input
              id="probe-status"
              type="number"
              placeholder="200"
              value={form.expected_status}
              onChange={(e) => set("expected_status", e.target.value)}
            />
          </Field>
          <Field id="probe-body" label={t("probe.field_expected_body")} full>
            <input
              id="probe-body"
              placeholder={t("teacher.probe_body_placeholder")}
              value={form.expected_body}
              onChange={(e) => set("expected_body", e.target.value)}
            />
          </Field>
        </>
      );
    case "tcp":
      return (
        <>
          <Field id="probe-host" label={t("probe.field_host")}>
            <input
              id="probe-host"
              placeholder={t("teacher.probe_host_placeholder")}
              value={form.tcp_host}
              onChange={(e) => set("tcp_host", e.target.value)}
            />
          </Field>
          <Field id="probe-port" label={t("probe.field_port")}>
            <input
              id="probe-port"
              type="number"
              placeholder="3306"
              value={form.tcp_port}
              onChange={(e) => set("tcp_port", e.target.value)}
            />
          </Field>
        </>
      );
    case "sql":
      return (
        <>
          <Field id="probe-query" label={t("probe.field_query")} full>
            <input
              id="probe-query"
              placeholder="SELECT count(*) FROM users"
              value={form.sql_query}
              onChange={(e) => set("sql_query", e.target.value)}
            />
          </Field>
          <Field id="probe-min-rows" label={t("teacher.probe_sql_min_rows")}>
            <input
              id="probe-min-rows"
              type="number"
              placeholder="1"
              value={form.sql_min_rows}
              onChange={(e) => set("sql_min_rows", e.target.value)}
            />
          </Field>
        </>
      );
    case "file":
      return (
        <>
          <Field id="probe-path" label={t("probe.field_path")} full>
            <input
              id="probe-path"
              placeholder="/etc/nginx/nginx.conf"
              value={form.file_path}
              onChange={(e) => set("file_path", e.target.value)}
            />
          </Field>
          <Field id="probe-contains" label={t("probe.field_contains")} full>
            <input
              id="probe-contains"
              placeholder="gzip on"
              value={form.file_contains}
              onChange={(e) => set("file_contains", e.target.value)}
            />
          </Field>
        </>
      );
    case "command":
      return (
        <>
          <Field id="probe-command" label={t("probe.field_command")} full>
            <input
              id="probe-command"
              placeholder="systemctl is-active apache2"
              value={form.cmd}
              onChange={(e) => set("cmd", e.target.value)}
            />
          </Field>
          <Field id="probe-exit" label={t("probe.field_exit_code")}>
            <input
              id="probe-exit"
              type="number"
              placeholder="0"
              value={form.expected_exit}
              onChange={(e) => set("expected_exit", e.target.value)}
            />
          </Field>
        </>
      );
    case "script":
      return <p className="muted text-sm field full">{t("teacher.probe_script_in_section")}</p>;
  }
}
