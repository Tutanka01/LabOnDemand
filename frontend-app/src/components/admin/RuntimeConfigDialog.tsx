import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { RuntimeConfig } from "../../types/api";
import { createRuntimeConfig, updateRuntimeConfig } from "../../lib/api";
import { Button, ErrorState, IconButton, LoadingState, showToast } from "../ui";

const schema = z.object({
  key: z.string().min(2).max(50),
  default_image: z.string().min(1),
  target_port: z.number().min(1).max(65535),
  default_service_type: z.enum(["ClusterIP", "NodePort", "LoadBalancer"]),
  allowed_for_students: z.boolean(),
  min_cpu_request: z.string(),
  min_memory_request: z.string(),
  min_cpu_limit: z.string(),
  min_memory_limit: z.string(),
  active: z.boolean(),
});

type FormData = z.infer<typeof schema>;

export function RuntimeConfigDialog({
  config,
  open,
  onOpenChange,
}: {
  config?: RuntimeConfig | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const isEdit = Boolean(config);

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      key: config?.key || "",
      default_image: config?.default_image || "",
      target_port: config?.target_port || 8080,
      default_service_type: (config?.default_service_type as FormData["default_service_type"]) || "NodePort",
      allowed_for_students: config?.allowed_for_students ?? true,
      min_cpu_request: config?.min_cpu_request || "100m",
      min_memory_request: config?.min_memory_request || "128Mi",
      min_cpu_limit: config?.min_cpu_limit || "200m",
      min_memory_limit: config?.min_memory_limit || "256Mi",
      active: config?.active ?? true,
    },
  });

  const createMut = useMutation({
    mutationFn: (data: FormData) => createRuntimeConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runtime-configs"] });
      showToast("Runtime cree", "success");
      onOpenChange(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: (data: FormData) => updateRuntimeConfig(config!.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runtime-configs"] });
      showToast("Runtime mis a jour", "success");
      onOpenChange(false);
    },
  });

  const mutation = isEdit ? updateMut : createMut;

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) form.reset(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel dialog-wide">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{isEdit ? "Modifier la config" : "Nouvelle config runtime"}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          {mutation.error ? <ErrorState>{mutation.error.message}</ErrorState> : null}

          <form className="form-grid" onSubmit={form.handleSubmit((data) => mutation.mutate(data))}>
            <div className="field"><label>Key</label><input {...form.register("key")} disabled={isEdit} /></div>
            <div className="field"><label>Image</label><input {...form.register("default_image")} /></div>
            <div className="field"><label>Port cible</label><input type="number" {...form.register("target_port", { valueAsNumber: true })} /></div>
            <div className="field">
              <label>Service</label>
              <select {...form.register("default_service_type")}>
                <option value="ClusterIP">ClusterIP</option>
                <option value="NodePort">NodePort</option>
                <option value="LoadBalancer">LoadBalancer</option>
              </select>
            </div>
            <div className="field"><label>CPU request</label><input {...form.register("min_cpu_request")} /></div>
            <div className="field"><label>Memory request</label><input {...form.register("min_memory_request")} /></div>
            <div className="field"><label>CPU limit</label><input {...form.register("min_cpu_limit")} /></div>
            <div className="field"><label>Memory limit</label><input {...form.register("min_memory_limit")} /></div>
            <div className="field">
              <label><input type="checkbox" {...form.register("allowed_for_students")} style={{ marginRight: 8 }} />Etudiants autorises</label>
            </div>
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
