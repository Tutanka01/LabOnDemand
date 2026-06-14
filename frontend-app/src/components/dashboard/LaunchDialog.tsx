import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Rocket, Sparkles, X } from "lucide-react";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { createDeployment, getQuotas, getResourcePresets } from "../../lib/api";
import { defaultRuntime } from "../../lib/format";
import { RuntimeIcon } from "../../lib/icons";
import type { PvcInfo, Template } from "../../types/api";
import { Button, ErrorState, FormField, IconButton, LoadingState, ResourceMeter } from "../ui";

const launchSchema = z.object({
  name: z.string().min(3, "Nom trop court").regex(/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/, "Nom DNS Kubernetes invalide"),
  cpu: z.string().min(1),
  ram: z.string().min(1),
  image: z.string().min(1, "Image requise"),
  replicas: z.number().min(1).max(5),
  createService: z.boolean(),
  serviceType: z.enum(["ClusterIP", "NodePort", "LoadBalancer"]),
  servicePort: z.number().min(1).max(65535),
  serviceTargetPort: z.number().min(1).max(65535),
  existingPvcName: z.string().optional(),
});

type LaunchForm = z.infer<typeof launchSchema>;

function parseCpuMillicores(value?: string) {
  if (!value) return 0;
  const raw = value.endsWith("m") ? value.slice(0, -1) : value;
  const numeric = Number(raw);
  if (Number.isNaN(numeric)) return 0;
  return value.endsWith("m") ? numeric : numeric * 1000;
}

function parseMemoryMi(value?: string) {
  if (!value) return 0;
  const numeric = Number(value.replace(/[^\d.]/g, ""));
  if (Number.isNaN(numeric)) return 0;
  if (value.toLowerCase().endsWith("gi")) return numeric * 1024;
  if (value.toLowerCase().endsWith("ki")) return numeric / 1024;
  return numeric;
}

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
  const quotas = useQuery({ queryKey: ["quotas"], queryFn: getQuotas, staleTime: 30_000 });
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
      createService: true,
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
      create_service: deploymentType === "custom" ? values.createService : true,
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
  const watchedCpu = form.watch("cpu");
  const watchedRam = form.watch("ram");
  const watchedReplicas = form.watch("replicas") || 1;
  const watchedCreateService = form.watch("createService");
  const [cpuRequest, cpuLimit] = (watchedCpu || "").split("|");
  const [memoryRequest, memoryLimit] = (watchedRam || "").split("|");
  const projected = useMemo(() => {
    const replicas = custom ? watchedReplicas : 1;
    const multiPod = deploymentType === "wordpress" || deploymentType === "mysql" || deploymentType === "lamp";
    const pods = multiPod ? 2 : replicas;
    const cpuM = parseCpuMillicores(cpuRequest) * pods;
    const memMi = parseMemoryMi(memoryRequest) * pods;
    return { apps: 1, pods, cpuM, memMi };
  }, [cpuRequest, custom, deploymentType, memoryRequest, watchedReplicas]);
  const quotaOverages = useMemo(() => {
    if (!quotas.data) return [];
    const over: string[] = [];
    if (quotas.data.usage.apps_used + projected.apps > quotas.data.limits.max_apps) over.push("applications");
    if (quotas.data.usage.cpu_m_used + projected.cpuM > quotas.data.limits.max_requests_cpu_m) over.push("CPU");
    if (quotas.data.usage.mem_mi_used + projected.memMi > quotas.data.limits.max_requests_mem_mi) over.push("mémoire");
    return over;
  }, [projected, quotas.data]);

  return (
    <Dialog.Root open onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel dialog-wide">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2 className="flex min-w-0 items-center gap-2.5">
                <span className="runtime-mark shrink-0">
                  <RuntimeIcon type={deploymentType} />
                </span>
                <span className="min-w-0">
                  <span className="block text-[0.72rem] font-semibold uppercase tracking-wider text-[var(--muted)]">
                    {deploymentType}
                  </span>
                  <span className="block truncate">Configurer {template.name}</span>
                </span>
              </h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer">
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>
          <form className="form-grid" onSubmit={submit}>
            <FormField label="Nom du déploiement" error={form.formState.errors.name?.message} full required>
              <input id="name" {...form.register("name")} />
            </FormField>

            <FormField label="CPU" full={false}>
              <select id="cpu" aria-disabled={student} tabIndex={student ? -1 : undefined} className={student ? "disabled" : undefined} {...form.register("cpu")}>
                {cpuPresets.map((preset) => (
                  <option value={optionValue(preset)} key={optionValue(preset)}>
                    {preset.label} ({preset.request}/{preset.limit})
                  </option>
                ))}
              </select>
            </FormField>

            <FormField label="Mémoire" full={false}>
              <select id="ram" aria-disabled={student} tabIndex={student ? -1 : undefined} className={student ? "disabled" : undefined} {...form.register("ram")}>
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
                <FormField label="Réplicas" full={false}>
                  <input
                    id="replicas"
                    type="number"
                    min={1}
                    max={student ? 1 : 5}
                    aria-disabled={student}
                    className={student ? "disabled" : undefined}
                    tabIndex={student ? -1 : undefined}
                    {...form.register("replicas", { valueAsNumber: true })}
                  />
                </FormField>
                <FormField label="Accès réseau" full={false}>
                  <label className="flex min-h-10 items-center gap-2 rounded-lg border border-[var(--border)] px-2.5">
                    <input type="checkbox" {...form.register("createService")} />
                    Créer un service Kubernetes
                  </label>
                </FormField>
                {watchedCreateService ? (
                  <>
                    <FormField label="Type de service" full={false}>
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
              </>
            ) : null}

            {pvcSupported ? (
              <FormField label="Volume persistant" full>
                <select id="existingPvcName" {...form.register("existingPvcName")}>
                  <option value="">Créer un nouveau volume</option>
                  {pvcs.map((pvc) => (
                    <option value={pvc.name} key={pvc.name}>
                      {pvc.name} - {pvc.storage || "taille inconnue"}
                    </option>
                  ))}
                </select>
              </FormField>
            ) : null}

            <div className="field full rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3.5 shadow-[var(--shadow-sm)]">
              <strong className="flex items-center gap-2">
                <Sparkles size={15} className="text-[var(--primary)]" />
                Résumé du lancement
              </strong>
              <div className="lab-meta mt-2">
                <span className="badge">Pods estimés: {projected.pods}</span>
                <span className="badge">CPU: {cpuRequest || "-"} / {cpuLimit || "-"}</span>
                <span className="badge">Mémoire: {memoryRequest || "-"} / {memoryLimit || "-"}</span>
              </div>
              {quotas.data ? (
                <div className="grid gap-2 pt-3">
                  <ResourceMeter label="Applications après lancement" used={quotas.data.usage.apps_used + projected.apps} max={quotas.data.limits.max_apps} />
                  <ResourceMeter label="CPU après lancement" used={quotas.data.usage.cpu_m_used + projected.cpuM} max={quotas.data.limits.max_requests_cpu_m} unit="m" />
                  <ResourceMeter label="Mémoire après lancement" used={quotas.data.usage.mem_mi_used + projected.memMi} max={quotas.data.limits.max_requests_mem_mi} unit="Mi" />
                </div>
              ) : null}
            </div>

            {presets.isLoading || quotas.isLoading ? <LoadingState label="Chargement des politiques de ressources" /> : null}
            {student ? <p className="muted field full">Les ressources CPU/RAM sont fixées par la politique étudiante côté serveur.</p> : null}
            {quotaOverages.length ? (
              <ErrorState title="Quota insuffisant">
                Le lancement dépasserait: {quotaOverages.join(", ")}.
              </ErrorState>
            ) : null}
            {createMutation.error ? <ErrorState>{createMutation.error.message}</ErrorState> : null}
            <div className="actions-row field full justify-end">
              <Button type="button" onClick={() => onOpenChange(false)}>Annuler</Button>
              <Button variant="primary" type="submit" disabled={createMutation.isPending || quotaOverages.length > 0}>
                <Rocket size={16} />
                {createMutation.isPending ? "Lancement..." : "Lancer le lab"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
