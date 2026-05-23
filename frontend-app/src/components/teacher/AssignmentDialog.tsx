import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { Assignment, Template } from "../../types/api";
import { createAssignment, getResourcePresets, updateAssignment } from "../../lib/api";
import { presetLabel } from "../../lib/format";
import { Button, ErrorState, IconButton, showToast } from "../ui";

const schema = z.object({
  title: z.string().min(2, "Minimum 2 caracteres").max(200),
  instructions: z.string().optional(),
  template_key: z.string().optional(),
  cpu_preset: z.enum(["very-low", "low", "medium", "high", "very-high"]),
  ram_preset: z.enum(["very-low", "low", "medium", "high", "very-high"]),
  due_at: z.string().optional(),
});

type FormData = z.infer<typeof schema>;

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
  const queryClient = useQueryClient();
  const isEdit = Boolean(assignment);
  const resourcePresets = useQuery({ queryKey: ["resource-presets"], queryFn: getResourcePresets, staleTime: 300_000 });

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: assignment?.title || "",
      instructions: assignment?.instructions || "",
      template_key: assignment?.template_key || "",
      cpu_preset: (assignment?.cpu_preset as FormData["cpu_preset"]) || "medium",
      ram_preset: (assignment?.ram_preset as FormData["ram_preset"]) || "medium",
      due_at: assignment?.due_at?.slice(0, 16) || "",
    },
  });

  const createMut = useMutation({
    mutationFn: (data: FormData) => createAssignment(classroomId, {
      title: data.title,
      instructions: data.instructions,
      template_key: data.template_key,
      cpu_preset: data.cpu_preset,
      ram_preset: data.ram_preset,
      due_at: data.due_at || undefined,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments", classroomId] });
      showToast("Devoir cree", "success");
      onOpenChange(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: (data: FormData) => updateAssignment(classroomId, assignment!.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments", classroomId] });
      showToast("Devoir mis a jour", "success");
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
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{isEdit ? "Modifier le devoir" : "Nouveau devoir"}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          {mutation.error ? <ErrorState>{mutation.error.message}</ErrorState> : null}

          <form className="form-grid" onSubmit={form.handleSubmit((data) => mutation.mutate(data))}>
            <div className="field full">
              <label htmlFor="title">Titre du devoir</label>
              <input id="title" {...form.register("title")} />
              {form.formState.errors.title ? <span className="badge red">{form.formState.errors.title.message}</span> : null}
            </div>
            <div className="field full">
              <label htmlFor="template_key">Template</label>
              <select id="template_key" {...form.register("template_key")}>
                <option value="">Selectionner un template (optionnel)</option>
                {templates.map((t) => (
                  <option key={t.key} value={t.key}>{t.name}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="cpu_preset">CPU Preset</label>
              <select id="cpu_preset" {...form.register("cpu_preset")}>
                {effectiveCpuOptions.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="ram_preset">RAM Preset</label>
              <select id="ram_preset" {...form.register("ram_preset")}>
                {effectiveRamOptions.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
            <div className="field full">
              <label htmlFor="instructions">Instructions (markdown)</label>
              <textarea
                className="min-h-[100px] resize-y"
                id="instructions"
                rows={5}
                placeholder="Decrivez le devoir en markdown..."
                {...form.register("instructions")}
              />
            </div>
            <div className="field">
              <label htmlFor="due_at">Date limite</label>
              <input id="due_at" type="datetime-local" {...form.register("due_at")} />
            </div>

            <div className="actions-row field full justify-end">
              <Button type="button" onClick={() => onOpenChange(false)}>Annuler</Button>
              <Button variant="primary" type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Enregistrement..." : isEdit ? "Mettre a jour" : "Creer le devoir"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
