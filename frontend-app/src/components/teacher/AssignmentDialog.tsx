import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Eye, FileText, Pencil, Plus, Trash2, Upload, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type {
  Assignment,
  GradingMode,
  Probe,
  ProbeKind,
  ProbeVantage,
  ProbeVisibility,
  Template,
} from "../../types/api";
import {
  createAssignment,
  getGradingSpec,
  getResourcePresets,
  saveGradingSpec,
  updateAssignment,
} from "../../lib/api";
import { presetLabel } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { Markdown } from "../Markdown";
import {
  Badge,
  Button,
  ErrorState,
  IconButton,
  TabContent,
  TabList,
  Tabs,
  TabTrigger,
  showToast,
} from "../ui";

// ─── Assignment form schema ───────────────────────────────────────────────────

const schema = z.object({
  title: z.string().min(2, "Minimum 2 caracteres").max(200),
  instructions: z.string().optional(),
  deliverables: z.string().optional(),
  template_key: z.string().optional(),
  cpu_preset: z.enum(["very-low", "low", "medium", "high", "very-high"]),
  ram_preset: z.enum(["very-low", "low", "medium", "high", "very-high"]),
  due_at: z.string().optional(),
});

type FormData = z.infer<typeof schema>;

// ─── Probe helpers ───────────────────────────────────────────────────────────

type ProbeFormState = {
  id: string;
  name: string;
  kind: ProbeKind;
  vantage: ProbeVantage;
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

function emptyProbeForm(): ProbeFormState {
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

function probeFormToProbe(f: ProbeFormState): Probe {
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

function probeToFormState(p: Probe): ProbeFormState {
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

const KIND_LABELS: Record<ProbeKind, string> = {
  http: "HTTP",
  tcp: "TCP",
  sql: "SQL",
  file: "Fichier",
  command: "Commande",
  script: "Script",
};

const VISIBILITY_TONES: Record<ProbeVisibility, "green" | "amber" | "blue"> = {
  student: "green",
  summary: "amber",
  teacher_only: "blue",
};

// ─── Markdown field with Write/Preview toggle ────────────────────────────────

function MarkdownField({
  label,
  hint,
  value,
  placeholder,
  rows = 7,
  register,
}: {
  label: string;
  hint?: string;
  value: string;
  placeholder?: string;
  rows?: number;
  register: ReturnType<ReturnType<typeof useForm<FormData>>["register"]>;
}) {
  const { t } = useI18n();
  const [preview, setPreview] = useState(false);
  return (
    <div className="field full">
      <div className="md-field-head">
        <label>{label}</label>
        <div className="md-tabs">
          <button type="button" className={!preview ? "active" : ""} onClick={() => setPreview(false)}>
            <Pencil size={13} /> {t("assignment.md_write")}
          </button>
          <button type="button" className={preview ? "active" : ""} onClick={() => setPreview(true)}>
            <Eye size={13} /> {t("assignment.md_preview")}
          </button>
        </div>
      </div>
      {preview ? (
        <div className="md-preview">
          {value.trim() ? <Markdown>{value}</Markdown> : <span className="muted">{t("assignment.md_empty")}</span>}
        </div>
      ) : (
        <textarea className="md-textarea" rows={rows} placeholder={placeholder} {...register} />
      )}
      {hint ? <span className="muted text-[0.78rem] mt-1">{hint}</span> : null}
    </div>
  );
}

// ─── Probe kind-specific config fields ───────────────────────────────────────

function ProbeConfigFields({ form, setForm }: { form: ProbeFormState; setForm: (f: ProbeFormState) => void }) {
  const { t } = useI18n();
  const set = (key: keyof ProbeFormState, val: string | number) => setForm({ ...form, [key]: val });

  switch (form.kind) {
    case "http":
      return (
        <>
          <div className="field full">
            <label>{t("probe.field_url")}</label>
            <input
              placeholder="http://lab-url/health"
              value={form.url}
              onChange={(e) => set("url", e.target.value)}
            />
          </div>
          <div className="field">
            <label>{t("probe.field_method")}</label>
            <select value={form.method} onChange={(e) => set("method", e.target.value)}>
              {["GET", "POST", "PUT", "DELETE", "HEAD"].map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>{t("probe.field_expected_status")}</label>
            <input
              type="number"
              placeholder="200"
              value={form.expected_status}
              onChange={(e) => set("expected_status", e.target.value)}
            />
          </div>
          <div className="field full">
            <label>{t("probe.field_expected_body")}</label>
            <input
              placeholder='Ex: "ok" ou {"status":"running"}'
              value={form.expected_body}
              onChange={(e) => set("expected_body", e.target.value)}
            />
          </div>
        </>
      );
    case "tcp":
      return (
        <>
          <div className="field">
            <label>{t("probe.field_host")}</label>
            <input
              placeholder="lab-url ou IP"
              value={form.tcp_host}
              onChange={(e) => set("tcp_host", e.target.value)}
            />
          </div>
          <div className="field">
            <label>{t("probe.field_port")}</label>
            <input
              type="number"
              placeholder="3306"
              value={form.tcp_port}
              onChange={(e) => set("tcp_port", e.target.value)}
            />
          </div>
        </>
      );
    case "sql":
      return (
        <>
          <div className="field full">
            <label>{t("probe.field_query")}</label>
            <input
              placeholder="SELECT count(*) FROM users"
              value={form.sql_query}
              onChange={(e) => set("sql_query", e.target.value)}
            />
          </div>
          <div className="field">
            <label>Résultats min attendus</label>
            <input
              type="number"
              placeholder="1"
              value={form.sql_min_rows}
              onChange={(e) => set("sql_min_rows", e.target.value)}
            />
          </div>
        </>
      );
    case "file":
      return (
        <>
          <div className="field full">
            <label>{t("probe.field_path")}</label>
            <input
              placeholder="/etc/nginx/nginx.conf"
              value={form.file_path}
              onChange={(e) => set("file_path", e.target.value)}
            />
          </div>
          <div className="field full">
            <label>{t("probe.field_contains")}</label>
            <input
              placeholder="gzip on"
              value={form.file_contains}
              onChange={(e) => set("file_contains", e.target.value)}
            />
          </div>
        </>
      );
    case "command":
      return (
        <>
          <div className="field full">
            <label>{t("probe.field_command")}</label>
            <input
              placeholder="systemctl is-active apache2"
              value={form.cmd}
              onChange={(e) => set("cmd", e.target.value)}
            />
          </div>
          <div className="field">
            <label>{t("probe.field_exit_code")}</label>
            <input
              type="number"
              placeholder="0"
              value={form.expected_exit}
              onChange={(e) => set("expected_exit", e.target.value)}
            />
          </div>
        </>
      );
    case "script":
      return (
        <p className="muted text-sm">
          Le script est défini dans la section « Script avancé » ci-dessous.
        </p>
      );
  }
}

// ─── Probe editor ────────────────────────────────────────────────────────────

function ProbeEditor({
  probes,
  onChange,
  customScript,
  onCustomScriptChange,
  gradingMode,
  onGradingModeChange,
  timeoutSeconds,
  onTimeoutChange,
}: {
  probes: Probe[];
  onChange: (probes: Probe[]) => void;
  customScript: string;
  onCustomScriptChange: (s: string) => void;
  gradingMode: GradingMode;
  onGradingModeChange: (m: GradingMode) => void;
  timeoutSeconds: number;
  onTimeoutChange: (s: number) => void;
}) {
  const { t } = useI18n();
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<ProbeFormState>(emptyProbeForm);
  const [scriptOpen, setScriptOpen] = useState(false);

  const openAdd = () => {
    setForm(emptyProbeForm());
    setEditingId(null);
    setFormOpen(true);
  };

  const openEdit = (p: Probe) => {
    setForm(probeToFormState(p));
    setEditingId(p.id);
    setFormOpen(true);
  };

  const handleConfirm = () => {
    if (!form.name.trim()) return;
    const probe = probeFormToProbe(form);
    if (editingId) {
      onChange(probes.map((p) => (p.id === editingId ? probe : p)));
    } else {
      onChange([...probes, { ...probe, id: `probe-${Date.now()}` }]);
    }
    setFormOpen(false);
    setEditingId(null);
  };

  const handleDelete = (id: string) => {
    onChange(probes.filter((p) => p.id !== id));
    if (editingId === id) setFormOpen(false);
  };

  return (
    <div className="probe-editor">
      {/* Grading mode + timeout */}
      <div className="form-grid" style={{ marginBottom: "1rem" }}>
        <div className="field">
          <label>{t("probe.grading_mode_label")}</label>
          <select value={gradingMode} onChange={(e) => onGradingModeChange(e.target.value as GradingMode)}>
            <option value="none">{t("probe.grading_mode_none")}</option>
            <option value="self_check">{t("probe.grading_mode_self_check")}</option>
            <option value="graded">{t("probe.grading_mode_graded")}</option>
          </select>
        </div>
        <div className="field">
          <label>{t("probe.timeout_label")}</label>
          <input
            type="number"
            min={10}
            max={600}
            value={timeoutSeconds}
            onChange={(e) => onTimeoutChange(Number(e.target.value))}
          />
        </div>
      </div>

      {/* Probe list */}
      {probes.length === 0 && !formOpen ? (
        <div className="probe-empty">
          <p className="muted">{t("probe.no_probes")}</p>
          <p className="muted text-sm">{t("probe.no_probes_hint")}</p>
        </div>
      ) : (
        <ul className="probe-list">
          {probes.map((p) => (
            <li key={p.id} className={`probe-card ${editingId === p.id ? "probe-card--editing" : ""}`}>
              <div className="probe-card__meta">
                <span className="badge">{KIND_LABELS[p.kind]}</span>
                <span className="probe-card__name">{p.name}</span>
              </div>
              <div className="probe-card__badges">
                <Badge tone={VISIBILITY_TONES[p.visibility]}>
                  {p.visibility === "student"
                    ? t("probe.visibility_student")
                    : p.visibility === "summary"
                      ? t("probe.visibility_summary")
                      : t("probe.visibility_teacher_only")}
                </Badge>
                <span className="muted text-sm">×{p.weight}</span>
              </div>
              <div className="probe-card__actions">
                <button
                  type="button"
                  className="btn-ghost-sm"
                  onClick={() => openEdit(p)}
                  title="Modifier"
                >
                  <Pencil size={14} />
                </button>
                <button
                  type="button"
                  className="btn-ghost-sm btn-ghost-sm--danger"
                  onClick={() => handleDelete(p.id)}
                  title={t("probe.delete")}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Add probe button */}
      {!formOpen && (
        <Button type="button" onClick={openAdd} className="probe-add-btn">
          <Plus size={15} /> {t("probe.add")}
        </Button>
      )}

      {/* Inline probe form */}
      {formOpen && (
        <div className="probe-form-panel">
          <div className="probe-form-panel__head">
            <strong>{editingId ? t("probe.form_title_edit") : t("probe.form_title_new")}</strong>
            <IconButton type="button" onClick={() => setFormOpen(false)} aria-label="Fermer">
              <X size={15} />
            </IconButton>
          </div>
          <div className="form-grid">
            {/* Common fields */}
            <div className="field full">
              <label>{t("probe.field_name")}</label>
              <input
                placeholder={t("probe.field_name_placeholder")}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                autoFocus
              />
            </div>
            <div className="field">
              <label>{t("probe.field_kind")}</label>
              <select
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value as ProbeKind })}
              >
                {(["http", "tcp", "sql", "file", "command", "script"] as ProbeKind[]).map((k) => (
                  <option key={k} value={k}>{t(`probe.kind_${k}`)}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>{t("probe.field_vantage")}</label>
              <select
                value={form.vantage}
                onChange={(e) => setForm({ ...form, vantage: e.target.value as ProbeVantage })}
              >
                <option value="outside">{t("probe.vantage_outside")}</option>
                <option value="inside">{t("probe.vantage_inside")}</option>
              </select>
            </div>
            <div className="field">
              <label>{t("probe.field_visibility")}</label>
              <select
                value={form.visibility}
                onChange={(e) => setForm({ ...form, visibility: e.target.value as ProbeVisibility })}
              >
                <option value="student">{t("probe.visibility_student")}</option>
                <option value="summary">{t("probe.visibility_summary")}</option>
                <option value="teacher_only">{t("probe.visibility_teacher_only")}</option>
              </select>
            </div>
            <div className="field">
              <label>{t("probe.field_weight")}</label>
              <input
                type="number"
                min={0}
                max={100}
                value={form.weight}
                onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })}
              />
            </div>
            {/* Kind-specific config */}
            <ProbeConfigFields form={form} setForm={setForm} />
          </div>
          <div className="actions-row justify-end" style={{ marginTop: "0.75rem" }}>
            <Button type="button" onClick={() => setFormOpen(false)}>
              {t("probe.cancel")}
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={handleConfirm}
              disabled={!form.name.trim()}
            >
              {t("probe.add_confirm")}
            </Button>
          </div>
        </div>
      )}

      {/* Advanced script accordion */}
      <div className="probe-script-section">
        <button
          type="button"
          className="probe-script-toggle"
          onClick={() => setScriptOpen((o) => !o)}
        >
          {scriptOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          {t("probe.script_tab")}
        </button>
        {scriptOpen && (
          <div className="probe-script-body">
            <label className="muted text-sm">{t("probe.script_hint")}</label>
            <textarea
              className="md-textarea"
              rows={8}
              placeholder={t("probe.script_placeholder")}
              value={customScript}
              onChange={(e) => onCustomScriptChange(e.target.value)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main AssignmentDialog ────────────────────────────────────────────────────

export function AssignmentDialog({
  classroomId,
  assignment,
  templates,
  open,
  onOpenChange,
}: {
  classroomId: number;
  assignment?: Assignment | null;
  templates: Template[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const isEdit = Boolean(assignment);
  const [activeTab, setActiveTab] = useState<"content" | "tests">("content");

  // Probe state (separate from RHF form)
  const [probes, setProbes] = useState<Probe[]>([]);
  const [customScript, setCustomScript] = useState("");
  const [gradingMode, setGradingMode] = useState<"none" | "self_check" | "graded">("none");
  const [timeoutSeconds, setTimeoutSeconds] = useState(120);

  const resourcePresets = useQuery({ queryKey: ["resource-presets"], queryFn: getResourcePresets, staleTime: 300_000 });

  // Load existing GradingSpec in edit mode
  const specQuery = useQuery({
    queryKey: ["grading-spec", classroomId, assignment?.id],
    queryFn: () => getGradingSpec(classroomId, assignment!.id),
    enabled: isEdit && Boolean(assignment?.id) && open,
    staleTime: 30_000,
  });

  // Sync spec into local state when loaded
  useEffect(() => {
    if (specQuery.data) {
      setProbes(specQuery.data.checks ?? []);
      setCustomScript(specQuery.data.custom_script ?? "");
      setTimeoutSeconds(specQuery.data.timeout_seconds ?? 120);
    }
  }, [specQuery.data]);

  useEffect(() => {
    if (assignment?.grading_mode) {
      setGradingMode(assignment.grading_mode as "none" | "self_check" | "graded");
    }
  }, [assignment?.grading_mode]);

  // Reset on close
  const resetAll = () => {
    form.reset();
    setProbes([]);
    setCustomScript("");
    setGradingMode("none");
    setTimeoutSeconds(120);
    setActiveTab("content");
  };

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: assignment?.title || "",
      instructions: assignment?.instructions || "",
      deliverables: assignment?.deliverables || "",
      template_key: assignment?.template_key || "",
      cpu_preset: (assignment?.cpu_preset as FormData["cpu_preset"]) || "medium",
      ram_preset: (assignment?.ram_preset as FormData["ram_preset"]) || "medium",
      due_at: assignment?.due_at?.slice(0, 16) || "",
    },
  });

  const instructionsValue = form.watch("instructions") || "";
  const deliverablesValue = form.watch("deliverables") || "";

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["assignments", classroomId] });
    queryClient.invalidateQueries({ queryKey: ["classrooms"] });
    queryClient.invalidateQueries({ queryKey: ["teacher-dashboard"] });
  };

  const saveSpec = async (aid: number) => {
    if (probes.length === 0 && !customScript.trim()) return;
    await saveGradingSpec(classroomId, aid, {
      timeout_seconds: timeoutSeconds,
      checks: probes,
      custom_script: customScript.trim() || null,
    });
  };

  const createMut = useMutation({
    mutationFn: async (data: FormData) => {
      const asgn = await createAssignment(classroomId, {
        title: data.title,
        instructions: data.instructions,
        deliverables: data.deliverables,
        template_key: data.template_key,
        cpu_preset: data.cpu_preset,
        ram_preset: data.ram_preset,
        due_at: data.due_at || undefined,
        grading_mode: gradingMode,
      });
      await saveSpec(asgn.id);
      return asgn;
    },
    onSuccess: () => {
      invalidate();
      showToast(t("assignment.created_ok"), "success");
      onOpenChange(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: async (data: FormData) => {
      await updateAssignment(classroomId, assignment!.id, { ...data, grading_mode: gradingMode });
      await saveSpec(assignment!.id);
      queryClient.invalidateQueries({ queryKey: ["grading-spec", classroomId, assignment!.id] });
    },
    onSuccess: () => {
      invalidate();
      showToast(t("assignment.updated_ok"), "success");
      onOpenChange(false);
    },
  });

  // Standalone "save tests" in edit mode (without touching assignment fields)
  const saveSpecMut = useMutation({
    mutationFn: () =>
      saveGradingSpec(classroomId, assignment!.id, {
        timeout_seconds: timeoutSeconds,
        checks: probes,
        custom_script: customScript.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["grading-spec", classroomId, assignment!.id] });
      showToast(t("probe.saved_ok"), "success");
    },
  });

  const mutation = isEdit ? updateMut : createMut;

  const presetKeys = ["very-low", "low", "medium", "high", "very-high"] as const;
  const cpuOptions = (resourcePresets.data?.cpu || []).map((preset, i) => ({
    value: presetKeys[i] || "medium",
    label: `${preset.label} (${preset.request}/${preset.limit})`,
  }));
  const ramOptions = (resourcePresets.data?.memory || []).map((preset, i) => ({
    value: presetKeys[i] || "medium",
    label: `${preset.label} (${preset.request}/${preset.limit})`,
  }));
  const fallbackOptions = presetKeys.map((p) => ({ value: p, label: presetLabel(p) }));
  const effectiveCpuOptions = cpuOptions.length ? cpuOptions : fallbackOptions;
  const effectiveRamOptions = ramOptions.length ? ramOptions : fallbackOptions;

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) resetAll();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel dialog-wide">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{isEdit ? t("assignment.edit_title") : t("assignment.create_title")}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label={t("common.close")}>
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>

          {mutation.error ? <ErrorState>{(mutation.error as Error).message}</ErrorState> : null}

          {/* Tab switcher */}
          <Tabs value={activeTab} onChange={(v) => setActiveTab(v as "content" | "tests")}>
            <TabList>
              <TabTrigger value="content">
                <FileText size={14} /> {t("assignment.statement")}
              </TabTrigger>
              <TabTrigger value="tests">
                {t("probe.tab_title")}
                {probes.length > 0 && (
                  <span className="badge" style={{ marginLeft: "0.35rem" }}>
                    {probes.length}
                  </span>
                )}
              </TabTrigger>
            </TabList>

            {/* ── Content tab ── */}
            <TabContent value="content">
              <form
                id="assignment-form"
                className="form-grid"
                onSubmit={form.handleSubmit((data) => mutation.mutate(data))}
              >
                <div className="field full">
                  <label htmlFor="title">{t("assignment.name")}</label>
                  <input
                    id="title"
                    placeholder={t("assignment.name_placeholder")}
                    {...form.register("title")}
                  />
                  {form.formState.errors.title ? (
                    <span className="badge red">{form.formState.errors.title.message}</span>
                  ) : null}
                </div>

                <MarkdownField
                  label={t("assignment.statement")}
                  hint={t("assignment.statement_hint")}
                  value={instructionsValue}
                  placeholder={t("assignment.statement_placeholder")}
                  rows={8}
                  register={form.register("instructions")}
                />

                <MarkdownField
                  label={t("assignment.deliverables")}
                  hint={t("assignment.deliverables_hint")}
                  value={deliverablesValue}
                  placeholder={t("assignment.deliverables_placeholder")}
                  rows={5}
                  register={form.register("deliverables")}
                />

                <div className="field full">
                  <div className="md-field-head">
                    <label>
                      <FileText size={14} className="inline mr-1" />
                      {t("assignment.environment")}
                    </label>
                  </div>
                </div>
                <div className="field full">
                  <label htmlFor="template_key">{t("assignment.template")}</label>
                  <select id="template_key" {...form.register("template_key")}>
                    <option value="">{t("assignment.template_placeholder")}</option>
                    {templates.map((tpl) => (
                      <option key={tpl.key} value={tpl.key}>
                        {tpl.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="cpu_preset">{t("assignment.cpu")}</label>
                  <select id="cpu_preset" {...form.register("cpu_preset")}>
                    {effectiveCpuOptions.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="ram_preset">{t("assignment.ram")}</label>
                  <select id="ram_preset" {...form.register("ram_preset")}>
                    {effectiveRamOptions.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field full">
                  <label htmlFor="due_at">{t("assignment.due_date")}</label>
                  <input id="due_at" type="datetime-local" {...form.register("due_at")} />
                </div>
              </form>
            </TabContent>

            {/* ── Tests tab ── */}
            <TabContent value="tests">
              <ProbeEditor
                probes={probes}
                onChange={setProbes}
                customScript={customScript}
                onCustomScriptChange={setCustomScript}
                gradingMode={gradingMode}
                onGradingModeChange={setGradingMode}
                timeoutSeconds={timeoutSeconds}
                onTimeoutChange={setTimeoutSeconds}
              />
            </TabContent>
          </Tabs>

          {/* Footer actions */}
          <div className="actions-row field full justify-end" style={{ marginTop: "1rem" }}>
            <Button type="button" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            {/* Standalone save-spec in edit mode */}
            {isEdit && activeTab === "tests" && (
              <Button
                type="button"
                onClick={() => saveSpecMut.mutate()}
                disabled={saveSpecMut.isPending}
              >
                {saveSpecMut.isPending ? t("probe.saving") : t("probe.save")}
              </Button>
            )}
            <Button
              variant="primary"
              type="submit"
              form="assignment-form"
              disabled={mutation.isPending}
            >
              <Upload size={16} />
              {mutation.isPending
                ? t("assignment.saving")
                : isEdit
                  ? t("assignment.update")
                  : t("assignment.create")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
