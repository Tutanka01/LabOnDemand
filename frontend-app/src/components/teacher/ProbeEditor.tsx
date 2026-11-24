import { ChevronDown, ChevronUp, Pencil, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../lib/i18n";
import type { GradingMode, Probe, ProbeKind, ProbeVisibility } from "../../types/api";
import { Badge, Button, IconButton } from "../ui";
import { ProbeConfigFields } from "./ProbeConfigFields";
import {
  emptyProbeForm,
  PROBE_KINDS,
  probeFormToProbe,
  type ProbeFormState,
  probeToFormState,
  VISIBILITY_TONES,
} from "./probeForm";

export type GradingSettings = {
  probes: Probe[];
  customScript: string;
  gradingMode: GradingMode;
  timeoutSeconds: number;
};

/** Automatic tests of an assignment: grading mode, list of probes, inline probe form, custom script. */
export function ProbeEditor({
  value,
  onChange,
}: {
  value: GradingSettings;
  onChange: (next: GradingSettings) => void;
}) {
  const { t } = useI18n();
  const { probes, customScript, gradingMode, timeoutSeconds } = value;
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<ProbeFormState>(emptyProbeForm);
  const [scriptOpen, setScriptOpen] = useState(Boolean(customScript));

  const update = (patch: Partial<GradingSettings>) => onChange({ ...value, ...patch });

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

  const closeForm = () => {
    setFormOpen(false);
    setEditingId(null);
  };

  const handleConfirm = () => {
    if (!form.name.trim()) return;
    const probe = probeFormToProbe(form);
    if (editingId) {
      update({ probes: probes.map((p) => (p.id === editingId ? probe : p)) });
    } else {
      update({ probes: [...probes, { ...probe, id: `probe-${Date.now()}` }] });
    }
    closeForm();
  };

  const handleDelete = (id: string) => {
    update({ probes: probes.filter((p) => p.id !== id) });
    if (editingId === id) closeForm();
  };

  const visibilityLabel = (v: ProbeVisibility) => t(`probe.visibility_${v}`);

  return (
    <div className="probe-editor">
      <div className="form-grid mb-4">
        <div className="field">
          <label htmlFor="grading-mode">{t("probe.grading_mode_label")}</label>
          <select
            id="grading-mode"
            value={gradingMode}
            onChange={(e) => update({ gradingMode: e.target.value as GradingMode })}
          >
            <option value="none">{t("probe.grading_mode_none")}</option>
            <option value="self_check">{t("probe.grading_mode_self_check")}</option>
            <option value="graded">{t("probe.grading_mode_graded")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="grading-timeout">{t("probe.timeout_label")}</label>
          <input
            id="grading-timeout"
            type="number"
            min={10}
            max={600}
            value={timeoutSeconds}
            onChange={(e) => update({ timeoutSeconds: Number(e.target.value) })}
          />
        </div>
      </div>

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
                <span className="badge">{t(`teacher.probe_short_${p.kind}`)}</span>
                <span className="probe-card__name">{p.name}</span>
              </div>
              <div className="probe-card__badges">
                <Badge tone={VISIBILITY_TONES[p.visibility]}>{visibilityLabel(p.visibility)}</Badge>
                <span className="muted text-sm" title={t("probe.field_weight")}>
                  ×{p.weight}
                </span>
              </div>
              <div className="probe-card__actions">
                <button
                  type="button"
                  className="btn-ghost-sm"
                  onClick={() => openEdit(p)}
                  title={t("probe.form_title_edit")}
                  aria-label={t("teacher.probe_edit_named", { name: p.name })}
                >
                  <Pencil size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="btn-ghost-sm btn-ghost-sm--danger"
                  onClick={() => handleDelete(p.id)}
                  title={t("probe.delete")}
                  aria-label={t("teacher.probe_delete_named", { name: p.name })}
                >
                  <Trash2 size={14} aria-hidden="true" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!formOpen && (
        <Button type="button" onClick={openAdd} className="probe-add-btn">
          <Plus size={15} aria-hidden="true" /> {t("probe.add")}
        </Button>
      )}

      {formOpen && (
        <div className="probe-form-panel">
          <div className="probe-form-panel__head">
            <strong>{editingId ? t("probe.form_title_edit") : t("probe.form_title_new")}</strong>
            <IconButton type="button" onClick={closeForm} aria-label={t("common.close")}>
              <X size={15} aria-hidden="true" />
            </IconButton>
          </div>
          <div className="form-grid">
            <div className="field full">
              <label htmlFor="probe-name">
                {t("probe.field_name")}
                <span className="required"> *</span>
              </label>
              <input
                id="probe-name"
                placeholder={t("probe.field_name_placeholder")}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                autoFocus
              />
            </div>
            <div className="field">
              <label htmlFor="probe-kind">{t("probe.field_kind")}</label>
              <select
                id="probe-kind"
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value as ProbeKind })}
              >
                {PROBE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`probe.kind_${k}`)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="probe-vantage">{t("probe.field_vantage")}</label>
              <select
                id="probe-vantage"
                value={form.vantage}
                onChange={(e) => setForm({ ...form, vantage: e.target.value as ProbeFormState["vantage"] })}
              >
                <option value="outside">{t("probe.vantage_outside")}</option>
                <option value="inside">{t("probe.vantage_inside")}</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="probe-visibility">{t("probe.field_visibility")}</label>
              <select
                id="probe-visibility"
                value={form.visibility}
                onChange={(e) => setForm({ ...form, visibility: e.target.value as ProbeVisibility })}
              >
                <option value="student">{t("probe.visibility_student")}</option>
                <option value="summary">{t("probe.visibility_summary")}</option>
                <option value="teacher_only">{t("probe.visibility_teacher_only")}</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="probe-weight">{t("probe.field_weight")}</label>
              <input
                id="probe-weight"
                type="number"
                min={0}
                max={100}
                value={form.weight}
                onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })}
              />
            </div>
            <ProbeConfigFields form={form} setForm={setForm} />
          </div>
          <div className="actions-row justify-end mt-3">
            <Button type="button" onClick={closeForm}>
              {t("probe.cancel")}
            </Button>
            <Button type="button" variant="primary" onClick={handleConfirm} disabled={!form.name.trim()}>
              {editingId ? t("teacher.probe_apply") : t("probe.add_confirm")}
            </Button>
          </div>
        </div>
      )}

      <div className="probe-script-section">
        <button
          type="button"
          className="probe-script-toggle"
          aria-expanded={scriptOpen}
          onClick={() => setScriptOpen((o) => !o)}
        >
          {scriptOpen ? <ChevronUp size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />}
          {t("probe.script_tab")}
        </button>
        {scriptOpen && (
          <div className="probe-script-body">
            <label htmlFor="probe-script" className="muted text-sm">
              {t("probe.script_hint")}
            </label>
            <textarea
              id="probe-script"
              className="md-textarea"
              rows={8}
              placeholder={t("probe.script_placeholder")}
              value={customScript}
              onChange={(e) => update({ customScript: e.target.value })}
            />
          </div>
        )}
      </div>
    </div>
  );
}
