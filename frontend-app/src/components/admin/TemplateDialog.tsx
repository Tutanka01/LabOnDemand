import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { Template } from "../../types/api";
import { createTemplate, updateTemplate } from "../../lib/api";
import { Button, ErrorState, IconButton, showToast } from "../ui";

const schema = z.object({
  key: z.string().min(2).max(50),
  name: z.string().min(2).max(100),
  description: z.string().max(255).optional(),
  icon: z.string().max(100).optional(),
  deployment_type: z.string().regex(/^[a-z0-9][a-z0-9\-]*$/),
  default_image: z.string(),
  default_port: z.number().min(1).max(65535),
  default_service_type: z.enum(["ClusterIP", "NodePort", "LoadBalancer"]),
  tags: z.string().optional(),
  active: z.boolean(),
});

type FormData = z.infer<typeof schema>;

export function TemplateDialog({
  template,
  open,
  onOpenChange,
}: {
  template?: Template | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const isEdit = Boolean(template);

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      key: template?.key || "",
      name: template?.name || "",
      description: template?.description || "",
      icon: template?.icon || "",
      deployment_type: template?.deployment_type || "custom",
      default_image: template?.default_image || "",
      default_port: Number(template?.default_port) || 80,
      default_service_type: (template?.default_service_type as FormData["default_service_type"]) || "NodePort",
      tags: (template?.tags || []).join(", "),
      active: template?.active !== false,
    },
  });

  const createMut = useMutation({
    mutationFn: (data: FormData) => createTemplate({
      ...data,
      tags: data.tags ? data.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      default_port: data.default_port,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates-all"] });
      showToast("Template cree", "success");
      onOpenChange(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: (data: FormData) => updateTemplate(template!.id!, {
      ...data,
      tags: data.tags ? data.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      default_port: data.default_port,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates-all"] });
      showToast("Template mis a jour", "success");
      onOpenChange(false);
    },
  });

  const mutation = isEdit ? updateMut : createMut;

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) form.reset(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{isEdit ? "Modifier le template" : "Nouveau template"}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          {mutation.error ? <ErrorState>{mutation.error.message}</ErrorState> : null}

          <form className="form-grid" onSubmit={form.handleSubmit((data) => mutation.mutate(data))}>
            <div className="field"><label>Key</label><input {...form.register("key")} disabled={isEdit} /></div>
            <div className="field"><label>Nom</label><input {...form.register("name")} /></div>
            <div className="field full"><label>Description</label><input {...form.register("description")} /></div>
            <div className="field"><label>Icone (emoji)</label><input {...form.register("icon")} /></div>
            <div className="field"><label>Type de deploiement</label><input {...form.register("deployment_type")} placeholder="custom, vscode, jupyter..." /></div>
            <div className="field"><label>Image par defaut</label><input {...form.register("default_image")} /></div>
            <div className="field"><label>Port par defaut</label><input type="number" {...form.register("default_port", { valueAsNumber: true })} /></div>
            <div className="field">
              <label>Type de service</label>
              <select {...form.register("default_service_type")}>
                <option value="ClusterIP">ClusterIP</option>
                <option value="NodePort">NodePort</option>
                <option value="LoadBalancer">LoadBalancer</option>
              </select>
            </div>
            <div className="field full"><label>Tags (separes par des virgules)</label><input {...form.register("tags")} /></div>
            <div className="field">
              <label><input type="checkbox" {...form.register("active")} style={{ marginRight: 8 }} />Actif</label>
            </div>
            <div className="actions-row field full" style={{ justifyContent: "end" }}>
              <Button type="button" onClick={() => onOpenChange(false)}>Annuler</Button>
              <Button variant="primary" type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "..." : isEdit ? "Mettre a jour" : "Creer"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
