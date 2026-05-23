import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { createDeployment } from "../../lib/api";
import { defaultRuntime, presetToResources } from "../../lib/format";
import type { PvcInfo, Template } from "../../types/api";
import { Button, ErrorState, FormField, IconButton } from "../ui";

const launchSchema = z.object({
  name: z.string().min(3, "Nom trop court").regex(/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/, "Nom DNS Kubernetes invalide"),
  cpu: z.enum(["very-low", "low", "medium", "high", "very-high"]),
  ram: z.enum(["very-low", "low", "medium", "high", "very-high"]),
  image: z.string().min(1, "Image requise"),
  replicas: z.number().min(1).max(5),
  serviceType: z.enum(["ClusterIP", "NodePort", "LoadBalancer"]),
  servicePort: z.number().min(1).max(65535),
  serviceTargetPort: z.number().min(1).max(65535),
  existingPvcName: z.string().optional(),
});

type LaunchForm = z.infer<typeof launchSchema>;

export function LaunchDialog({
  template,
  pvcs,
  student,
  onOpenChange,
  onCreated,
}: {
  template: Template;
  pvcs: PvcInfo[];
  student: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => Promise<void>;
}) {
  const deploymentType = template.deployment_type || template.key || String(template.id || "custom");
  const runtime = defaultRuntime(deploymentType);
  const createMutation = useMutation({ mutationFn: createDeployment, onSuccess: onCreated });

  const suffix = Math.floor(Math.random() * 9000) + 1000;
  const form = useForm<LaunchForm>({
    resolver: zodResolver(launchSchema),
    defaultValues: {
      name: `${deploymentType}-${suffix}`.toLowerCase().replace(/[^a-z0-9-]/g, "-"),
      cpu: student && deploymentType === "vscode" ? "low" : "medium",
      ram: "medium",
      image: template.default_image || runtime.image,
      replicas: 1,
      serviceType: (template.default_service_type as LaunchForm["serviceType"]) || (runtime.serviceType as LaunchForm["serviceType"]),
      servicePort: Number(template.default_port || runtime.port),
      serviceTargetPort: Number(template.default_port || runtime.target),
      existingPvcName: "",
    },
  });

  const submit = form.handleSubmit((values) => {
    const resources = presetToResources(values.cpu, values.ram);
    createMutation.mutate({
      name: values.name,
      image: values.image,
      replicas: values.replicas,
      create_service: deploymentType !== "custom" ? true : values.serviceType !== "ClusterIP",
      service_port: values.servicePort,
      service_target_port: values.serviceTargetPort,
      service_type: values.serviceType,
      deployment_type: deploymentType,
      cpu_request: resources.cpu.request,
      cpu_limit: resources.cpu.limit,
      memory_request: resources.memory.request,
      memory_limit: resources.memory.limit,
      existing_pvc_name: values.existingPvcName || undefined,
    });
  });

  const pvcSupported = deploymentType === "vscode" || deploymentType === "jupyter";
  const custom = deploymentType === "custom";

  return (
    <Dialog.Root open onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>Configurer {template.name}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer">
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>
          <form className="form-grid" onSubmit={submit}>
            <FormField label="Nom du deploiement" error={form.formState.errors.name?.message} full required>
              <input id="name" {...form.register("name")} />
            </FormField>

            <FormField label="CPU" full={false}>
              <select id="cpu" disabled={student} {...form.register("cpu")}>
                <option value="very-low">0.1 vCPU</option>
                <option value="low">0.25 vCPU</option>
                <option value="medium">0.5 vCPU</option>
                <option value="high">1 vCPU</option>
                <option value="very-high">2 vCPU</option>
              </select>
            </FormField>

            <FormField label="Memoire" full={false}>
              <select id="ram" disabled={student} {...form.register("ram")}>
                <option value="very-low">128 Mi</option>
                <option value="low">256 Mi</option>
                <option value="medium">512 Mi</option>
                <option value="high">1 Gi</option>
                <option value="very-high">2 Gi</option>
              </select>
            </FormField>

            {custom ? (
              <>
                <FormField label="Image Docker" full required>
                  <input id="image" {...form.register("image")} />
                </FormField>
                <FormField label="Replicas" full={false}>
                  <input
                    id="replicas"
                    type="number"
                    min={1}
                    max={student ? 1 : 5}
                    disabled={student}
                    {...form.register("replicas", { valueAsNumber: true })}
                  />
                </FormField>
                <FormField label="Service" full={false}>
                  <select id="serviceType" {...form.register("serviceType")}>
                    <option value="ClusterIP">ClusterIP</option>
                    <option value="NodePort">NodePort</option>
                    <option value="LoadBalancer">LoadBalancer</option>
                  </select>
                </FormField>
                <FormField label="Port externe" full={false}>
                  <input id="servicePort" type="number" {...form.register("servicePort", { valueAsNumber: true })} />
                </FormField>
                <FormField label="Port conteneur" full={false}>
                  <input id="serviceTargetPort" type="number" {...form.register("serviceTargetPort", { valueAsNumber: true })} />
                </FormField>
              </>
            ) : null}

            {pvcSupported ? (
              <FormField label="Volume persistant" full>
                <select id="existingPvcName" {...form.register("existingPvcName")}>
                  <option value="">Creer un nouveau volume</option>
                  {pvcs.map((pvc) => (
                    <option value={pvc.name} key={pvc.name}>
                      {pvc.name} - {pvc.storage || "taille inconnue"}
                    </option>
                  ))}
                </select>
              </FormField>
            ) : null}

            {student ? <p className="muted field full">Les ressources CPU/RAM sont fixees par la politique etudiante.</p> : null}
            {createMutation.error ? <ErrorState>{createMutation.error.message}</ErrorState> : null}
            <div className="actions-row field full" style={{ justifyContent: "end" }}>
              <Button type="button" onClick={() => onOpenChange(false)}>Annuler</Button>
              <Button variant="primary" type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? "Lancement..." : "Lancer le lab"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
