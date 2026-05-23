import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { createDeployment, getResourcePresets } from "../../lib/api";
import { defaultRuntime } from "../../lib/format";
import type { PvcInfo, Template } from "../../types/api";
import { Button, ErrorState, FormField, IconButton, LoadingState } from "../ui";

const launchSchema = z.object({
  name: z.string().min(3, "Nom trop court").regex(/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/, "Nom DNS Kubernetes invalide"),
  cpu: z.string().min(1),
  ram: z.string().min(1),
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
  onCreated: (created: { namespace?: string; deployment_type?: string }, name: string) => Promise<void>;
}) {
  const deploymentType = template.deployment_type || template.key || String(template.id || "custom");
  const runtime = defaultRuntime(deploymentType);
  const presets = useQuery({ queryKey: ["resource-presets"], queryFn: getResourcePresets, staleTime: 300_000 });
  const createMutation = useMutation({
    mutationFn: createDeployment,
    onSuccess: (created, variables) => onCreated(created, variables.name),
  });
  const cpuPresets = presets.data?.cpu?.length ? presets.data.cpu : [
    { label: "0.25 vCPU", request: "250m", limit: "500m" },
    { label: "0.5 vCPU", request: "500m", limit: "1000m" },
  ];
  const memoryPresets = presets.data?.memory?.length ? presets.data.memory : [
    { label: "256 Mi", request: "256Mi", limit: "512Mi" },
    { label: "512 Mi", request: "512Mi", limit: "1Gi" },
  ];
  const optionValue = (preset: { request: string; limit: string }) => `${preset.request}|${preset.limit}`;

  const suffix = Math.floor(Math.random() * 9000) + 1000;
  const form = useForm<LaunchForm>({
    resolver: zodResolver(launchSchema),
    defaultValues: {
      name: `${deploymentType}-${suffix}`.toLowerCase().replace(/[^a-z0-9-]/g, "-"),
      cpu: optionValue(cpuPresets[Math.min(student && deploymentType === "vscode" ? 0 : 1, cpuPresets.length - 1)]),
      ram: optionValue(memoryPresets[Math.min(1, memoryPresets.length - 1)]),
      image: template.default_image || runtime.image,
      replicas: 1,
      serviceType: (template.default_service_type as LaunchForm["serviceType"]) || (runtime.serviceType as LaunchForm["serviceType"]),
      servicePort: Number(template.default_port || runtime.port),
      serviceTargetPort: Number(template.default_port || runtime.target),
      existingPvcName: "",
    },
  });

  const submit = form.handleSubmit((values) => {
    const [cpuRequest, cpuLimit] = values.cpu.split("|");
    const [memoryRequest, memoryLimit] = values.ram.split("|");
    createMutation.mutate({
      name: values.name,
      image: values.image,
      replicas: values.replicas,
      create_service: deploymentType !== "custom" ? true : values.serviceType !== "ClusterIP",
      service_port: values.servicePort,
      service_target_port: values.serviceTargetPort,
      service_type: values.serviceType,
      deployment_type: deploymentType,
      cpu_request: cpuRequest,
      cpu_limit: cpuLimit,
      memory_request: memoryRequest,
      memory_limit: memoryLimit,
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
                {cpuPresets.map((preset) => (
                  <option value={optionValue(preset)} key={optionValue(preset)}>
                    {preset.label} ({preset.request}/{preset.limit})
                  </option>
                ))}
              </select>
            </FormField>

            <FormField label="Memoire" full={false}>
              <select id="ram" disabled={student} {...form.register("ram")}>
                {memoryPresets.map((preset) => (
                  <option value={optionValue(preset)} key={optionValue(preset)}>
                    {preset.label} ({preset.request}/{preset.limit})
                  </option>
                ))}
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

            {presets.isLoading ? <LoadingState label="Chargement des presets ressources" /> : null}
            {student ? <p className="muted field full">Les ressources CPU/RAM sont fixees par la politique etudiante.</p> : null}
            {createMutation.error ? <ErrorState>{createMutation.error.message}</ErrorState> : null}
            <div className="actions-row field full justify-end">
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
