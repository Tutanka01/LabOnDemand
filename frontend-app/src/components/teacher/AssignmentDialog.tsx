import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, FileText, Pencil, Upload, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { Assignment, Template } from "../../types/api";
import { createAssignment, getResourcePresets, updateAssignment } from "../../lib/api";
import { presetLabel } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { Markdown } from "../Markdown";
import { Button, ErrorState, IconButton, showToast } from "../ui";

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

/** Champ Markdown avec bascule Écrire / Aperçu. */
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
  const resourcePresets = useQuery({ queryKey: ["resource-presets"], queryFn: getResourcePresets, staleTime: 300_000 });

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

  // Suivre les valeurs pour l'aperçu Markdown en direct.
  const instructionsValue = form.watch("instructions") || "";
  const deliverablesValue = form.watch("deliverables") || "";

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["assignments", classroomId] });
    queryClient.invalidateQueries({ queryKey: ["classrooms"] });
    queryClient.invalidateQueries({ queryKey: ["teacher-dashboard"] });
  };

  const createMut = useMutation({
    mutationFn: (data: FormData) =>
      createAssignment(classroomId, {
        title: data.title,
        instructions: data.instructions,
        deliverables: data.deliverables,
        template_key: data.template_key,
        cpu_preset: data.cpu_preset,
        ram_preset: data.ram_preset,
        due_at: data.due_at || undefined,
      }),
    onSuccess: () => {
      invalidate();
      showToast(t("assignment.created_ok"), "success");
      onOpenChange(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: (data: FormData) => updateAssignment(classroomId, assignment!.id, data),
    onSuccess: () => {
      invalidate();
      showToast(t("assignment.updated_ok"), "success");
      onOpenChange(false);
    },
  });

  const mutation = isEdit ? updateMut : createMut;
  const presetKeys = ["very-low", "low", "medium", "high", "very-high"] as const;
  const cpuOptions = (resourcePresets.data?.cpu || []).map((preset, index) => ({
    value: presetKeys[index] || "medium",
    label: `${preset.label} (${preset.request}/${preset.limit})`,
  }));
  const ramOptions = (resourcePresets.data?.memory || []).map((preset, index) => ({
    value: presetKeys[index] || "medium",
    label: `${preset.label} (${preset.request}/${preset.limit})`,
  }));
  const fallbackOptions = presetKeys.map((p) => ({ value: p, label: presetLabel(p) }));
  const effectiveCpuOptions = cpuOptions.length ? cpuOptions : fallbackOptions;
  const effectiveRamOptions = ramOptions.length ? ramOptions : fallbackOptions;

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) form.reset(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel dialog-wide">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{isEdit ? t("assignment.edit_title") : t("assignment.create_title")}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label={t("common.close")}><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          {mutation.error ? <ErrorState>{mutation.error.message}</ErrorState> : null}

          <form className="form-grid" onSubmit={form.handleSubmit((data) => mutation.mutate(data))}>
            <div className="field full">
              <label htmlFor="title">{t("assignment.name")}</label>
              <input id="title" placeholder={t("assignment.name_placeholder")} {...form.register("title")} />
              {form.formState.errors.title ? <span className="badge red">{form.formState.errors.title.message}</span> : null}
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
                <label><FileText size={14} className="inline mr-1" />{t("assignment.environment")}</label>
              </div>
            </div>
            <div className="field full">
              <label htmlFor="template_key">{t("assignment.template")}</label>
              <select id="template_key" {...form.register("template_key")}>
                <option value="">{t("assignment.template_placeholder")}</option>
                {templates.map((tpl) => (
                  <option key={tpl.key} value={tpl.key}>{tpl.name}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="cpu_preset">{t("assignment.cpu")}</label>
              <select id="cpu_preset" {...form.register("cpu_preset")}>
                {effectiveCpuOptions.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="ram_preset">{t("assignment.ram")}</label>
              <select id="ram_preset" {...form.register("ram_preset")}>
                {effectiveRamOptions.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
            <div className="field full">
              <label htmlFor="due_at">{t("assignment.due_date")}</label>
              <input id="due_at" type="datetime-local" {...form.register("due_at")} />
            </div>

            <div className="actions-row field full justify-end">
              <Button type="button" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
              <Button variant="primary" type="submit" disabled={mutation.isPending}>
                <Upload size={16} />
                {mutation.isPending ? t("assignment.saving") : isEdit ? t("assignment.update") : t("assignment.create")}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
