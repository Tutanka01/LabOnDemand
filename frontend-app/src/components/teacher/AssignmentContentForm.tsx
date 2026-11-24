import { useQuery } from "@tanstack/react-query";
import { Eye, FileText, Pencil } from "lucide-react";
import { useState } from "react";
import type { UseFormRegisterReturn, UseFormReturn } from "react-hook-form";
import { z } from "zod";
import { getResourcePresets } from "../../lib/api";
import { presetLabel } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { Assignment, Template } from "../../types/api";
import { Markdown } from "../Markdown";

const PRESET_KEYS = ["very-low", "low", "medium", "high", "very-high"] as const;

// Validation messages are translation keys, resolved with t() when displayed.
export const assignmentSchema = z.object({
  title: z.string().min(2, "teacher.validation_min_2").max(200, "teacher.validation_max_200"),
  instructions: z.string().optional(),
  deliverables: z.string().optional(),
  template_key: z.string().optional(),
  cpu_preset: z.enum(PRESET_KEYS),
  ram_preset: z.enum(PRESET_KEYS),
  due_at: z.string().optional(),
});

export type AssignmentFormData = z.infer<typeof assignmentSchema>;

export function assignmentDefaults(assignment?: Assignment | null): AssignmentFormData {
  return {
    title: assignment?.title || "",
    instructions: assignment?.instructions || "",
    deliverables: assignment?.deliverables || "",
    template_key: assignment?.template_key || "",
    cpu_preset: (assignment?.cpu_preset as AssignmentFormData["cpu_preset"]) || "medium",
    ram_preset: (assignment?.ram_preset as AssignmentFormData["ram_preset"]) || "medium",
    due_at: assignment?.due_at?.slice(0, 16) || "",
  };
}

/** Textarea with a Write / Preview toggle rendering Markdown. */
function MarkdownField({
  id,
  label,
  hint,
  value,
  placeholder,
  rows = 7,
  register,
}: {
  id: string;
  label: string;
  hint?: string;
  value: string;
  placeholder?: string;
  rows?: number;
  register: UseFormRegisterReturn;
}) {
  const { t } = useI18n();
  const [preview, setPreview] = useState(false);
  return (
    <div className="field full">
      <div className="md-field-head">
        <label htmlFor={id}>{label}</label>
        <div className="md-tabs" role="group" aria-label={label}>
          <button type="button" className={!preview ? "active" : ""} aria-pressed={!preview} onClick={() => setPreview(false)}>
            <Pencil size={13} aria-hidden="true" /> {t("assignment.md_write")}
          </button>
          <button type="button" className={preview ? "active" : ""} aria-pressed={preview} onClick={() => setPreview(true)}>
            <Eye size={13} aria-hidden="true" /> {t("assignment.md_preview")}
          </button>
        </div>
      </div>
      {preview ? (
        <div className="md-preview">
          {value.trim() ? <Markdown>{value}</Markdown> : <span className="muted">{t("assignment.md_empty")}</span>}
        </div>
      ) : (
        <textarea
          id={id}
          className="md-textarea"
          rows={rows}
          placeholder={placeholder}
          aria-describedby={hint ? `${id}-hint` : undefined}
          {...register}
        />
      )}
      {hint ? (
        <span id={`${id}-hint`} className="muted text-xs mt-1">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

/** "Statement" tab of the assignment dialog: title, statement, deliverables, environment, due date. */
export function AssignmentContentForm({
  form,
  templates,
  onSubmit,
}: {
  form: UseFormReturn<AssignmentFormData>;
  templates: Template[];
  onSubmit: () => void;
}) {
  const { t } = useI18n();
  const resourcePresets = useQuery({ queryKey: ["resource-presets"], queryFn: getResourcePresets, staleTime: 300_000 });

  const toOptions = (presets?: Array<{ label: string; request: string; limit: string }>) =>
    (presets || []).map((preset, i) => ({
      value: PRESET_KEYS[i] || "medium",
      label: `${preset.label} (${preset.request}/${preset.limit})`,
    }));
  const fallbackOptions = PRESET_KEYS.map((p) => ({ value: p, label: presetLabel(p) }));
  const cpuOptions = toOptions(resourcePresets.data?.cpu);
  const ramOptions = toOptions(resourcePresets.data?.memory);
  const effectiveCpuOptions = cpuOptions.length ? cpuOptions : fallbackOptions;
  const effectiveRamOptions = ramOptions.length ? ramOptions : fallbackOptions;

  const titleError = form.formState.errors.title?.message;

  return (
    <form
      id="assignment-form"
      className="form-grid"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="field full">
        <label htmlFor="assignment-title">
          {t("assignment.name")}
          <span className="required"> *</span>
        </label>
        <input
          id="assignment-title"
          placeholder={t("assignment.name_placeholder")}
          aria-invalid={Boolean(titleError)}
          aria-describedby={titleError ? "assignment-title-error" : undefined}
          {...form.register("title")}
        />
        {titleError ? (
          <span id="assignment-title-error" className="badge red">
            {t(titleError)}
          </span>
        ) : null}
      </div>

      <MarkdownField
        id="assignment-instructions"
        label={t("assignment.statement")}
        hint={t("assignment.statement_hint")}
        value={form.watch("instructions") || ""}
        placeholder={t("assignment.statement_placeholder")}
        rows={8}
        register={form.register("instructions")}
      />

      <MarkdownField
        id="assignment-deliverables"
        label={t("assignment.deliverables")}
        hint={t("assignment.deliverables_hint")}
        value={form.watch("deliverables") || ""}
        placeholder={t("assignment.deliverables_placeholder")}
        rows={5}
        register={form.register("deliverables")}
      />

      <div className="field full">
        <div className="md-field-head">
          <strong className="text-sm">
            <FileText size={14} className="inline mr-1" aria-hidden="true" />
            {t("assignment.environment")}
          </strong>
        </div>
      </div>
      <div className="field full">
        <label htmlFor="assignment-template">{t("assignment.template")}</label>
        <select id="assignment-template" {...form.register("template_key")}>
          <option value="">{t("assignment.template_placeholder")}</option>
          {templates.map((tpl) => (
            <option key={tpl.key} value={tpl.key}>
              {tpl.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="assignment-cpu">{t("assignment.cpu")}</label>
        <select id="assignment-cpu" {...form.register("cpu_preset")}>
          {effectiveCpuOptions.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="assignment-ram">{t("assignment.ram")}</label>
        <select id="assignment-ram" {...form.register("ram_preset")}>
          {effectiveRamOptions.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
      <div className="field full">
        <label htmlFor="assignment-due">{t("assignment.due_date")}</label>
        <input id="assignment-due" type="datetime-local" {...form.register("due_at")} />
      </div>
    </form>
  );
}
