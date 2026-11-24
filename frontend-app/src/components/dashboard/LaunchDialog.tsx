import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronRight, Loader2, Lock, Rocket, Sparkles, X } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { createDeployment, getQuotas, getResourcePresets } from "../../lib/api";
import { cpuLabel, defaultRuntime, memoryLabel, parseCpuMillicores, parseMemoryMi } from "../../lib/format";
import { RuntimeIcon } from "../../lib/icons";
import { useI18n } from "../../lib/i18n";
import type { PvcInfo, Quotas, ResourcePreset, Template } from "../../types/api";
import { Button, ErrorState, IconButton, LoadingState, ResourceMeter, cn } from "../ui";

type Translate = (key: string, replacements?: Record<string, string | number>) => string;

const SERVICE_TYPES = ["ClusterIP", "NodePort", "LoadBalancer"] as const;
const PVC_TYPES = ["vscode", "jupyter", "netbeans", "eclipse"];
const DESKTOP_TYPES = ["netbeans", "eclipse"];
const MULTI_POD_TYPES = ["wordpress", "mysql", "lamp"];

const FALLBACK_CPU: ResourcePreset[] = [
  { label: "0.25 vCPU", request: "250m", limit: "500m" },
  { label: "0.5 vCPU", request: "500m", limit: "1000m" },
];
const FALLBACK_MEMORY: ResourcePreset[] = [
  { label: "256 Mi", request: "256Mi", limit: "512Mi" },
  { label: "512 Mi", request: "512Mi", limit: "1Gi" },
];

function makeSchema(t: Translate) {
  return z.object({
    name: z
      .string()
      .min(3, t("launch.name_too_short"))
      .regex(/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/, t("launch.name_invalid")),
    cpu: z.string().min(1),
    ram: z.string().min(1),
    image: z.string().min(1, t("launch.image_required")),
    replicas: z.number().min(1).max(5),
    createService: z.boolean(),
    serviceType: z.enum(SERVICE_TYPES),
    servicePort: z.number().min(1).max(65535),
    serviceTargetPort: z.number().min(1).max(65535),
    existingPvcName: z.string().optional(),
  });
}

type LaunchForm = z.infer<ReturnType<typeof makeSchema>>;

const optionValue = (preset: { request: string; limit: string }) => `${preset.request}|${preset.limit}`;

type SizeKey = "small" | "standard" | "large";
interface SizeOption {
  key: SizeKey;
  cpu: ResourcePreset;
  memory: ResourcePreset;
}

/** Three understandable sizes built from the role's presets (the server enforces the limits). */
function buildSizes(cpu: ResourcePreset[], memory: ResourcePreset[]): SizeOption[] {
  const pick = (list: ResourcePreset[], index: number) => list[Math.min(index, list.length - 1)];
  const sizes: SizeOption[] = (["small", "standard", "large"] as const).map((key, index) => ({
    key,
    cpu: pick(cpu, index),
    memory: pick(memory, index),
  }));
  return sizes.filter(
    (size, index) =>
      sizes.findIndex((other) => optionValue(other.cpu) === optionValue(size.cpu) && optionValue(other.memory) === optionValue(size.memory)) === index,
  );
}

/** "vscode", then "vscode-2", "vscode-3"… among the user's current labs. */
export function defaultLabName(deploymentType: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  let base =
    deploymentType
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "") || "lab";
  if (base.length < 3) base = `${base}-lab`;
  base = base.slice(0, 40).replace(/-$/, "");
  if (!used.has(base)) return base;
  for (let index = 2; index < 100; index += 1) {
    if (!used.has(`${base}-${index}`)) return `${base}-${index}`;
  }
  return `${base}-${Date.now() % 10_000}`;
}

export function LaunchDialog({
  template,
  pvcs,
  student,
  existingNames,
  onOpenChange,
  onCreated,
}: {
  template: Template;
  pvcs: PvcInfo[];
  student: boolean;
  /** Names of the user's current labs, to propose a free default name. */
  existingNames: string[];
  onOpenChange: (open: boolean) => void;
  onCreated: (created: { namespace?: string; deployment_type?: string }, name: string) => void | Promise<void>;
}) {
  const { t } = useI18n();
  const deploymentType = template.deployment_type || template.key || String(template.id || "custom");
  const presets = useQuery({ queryKey: ["resource-presets"], queryFn: getResourcePresets, staleTime: 300_000 });
  const quotas = useQuery({ queryKey: ["quotas"], queryFn: getQuotas, staleTime: 30_000 });

  return (
    <Dialog.Root open onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel dialog-wide" aria-describedby={undefined}>
          <div className="section-head">
            <Dialog.Title asChild>
              <h2 className="flex min-w-0 items-center gap-2.5">
                <span className="runtime-mark shrink-0">
                  <RuntimeIcon type={deploymentType} />
                </span>
                <span className="min-w-0">
                  <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
                    {t("launch.eyebrow")}
                  </span>
                  <span className="block truncate">{template.name || deploymentType}</span>
                </span>
              </h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label={t("common.close")}>
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>
          {presets.isLoading ? (
            <LoadingState label={t("launch.loading_policy")} />
          ) : (
            <LaunchForm
              template={template}
              deploymentType={deploymentType}
              cpuPresets={presets.data?.cpu?.length ? presets.data.cpu : FALLBACK_CPU}
              memoryPresets={presets.data?.memory?.length ? presets.data.memory : FALLBACK_MEMORY}
              quotas={quotas.data}
              pvcs={pvcs}
              student={student}
              existingNames={existingNames}
              onCancel={() => onOpenChange(false)}
              onCreated={onCreated}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function LaunchForm({
  template,
  deploymentType,
  cpuPresets,
  memoryPresets,
  quotas,
  pvcs,
  student,
  existingNames,
  onCancel,
  onCreated,
}: {
  template: Template;
  deploymentType: string;
  cpuPresets: ResourcePreset[];
  memoryPresets: ResourcePreset[];
  quotas?: Quotas;
  pvcs: PvcInfo[];
  student: boolean;
  existingNames: string[];
  onCancel: () => void;
  onCreated: (created: { namespace?: string; deployment_type?: string }, name: string) => void | Promise<void>;
}) {
  const { t, locale } = useI18n();
  const runtime = defaultRuntime(deploymentType);
  const custom = deploymentType === "custom";
  const pvcSupported = PVC_TYPES.includes(deploymentType);
  const hasAdvanced = !student || custom;
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const schema = useMemo(() => makeSchema(t), [t]);

  const createMutation = useMutation({
    mutationFn: createDeployment,
    onSuccess: (created, variables) => onCreated(created, variables.name),
  });

  const sizes = useMemo(() => buildSizes(cpuPresets, memoryPresets), [cpuPresets, memoryPresets]);

  const form = useForm<LaunchForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: defaultLabName(deploymentType, existingNames),
      cpu: optionValue(cpuPresets[Math.min(student && deploymentType === "vscode" ? 0 : 1, cpuPresets.length - 1)]),
      ram: optionValue(memoryPresets[Math.min(1, memoryPresets.length - 1)]),
      image: template.default_image || runtime.image,
      replicas: 1,
      createService: true,
      serviceType:
        (SERVICE_TYPES as readonly string[]).includes(template.default_service_type || "")
          ? (template.default_service_type as LaunchForm["serviceType"])
          : (runtime.serviceType as LaunchForm["serviceType"]),
      servicePort: Number(template.default_port || runtime.port),
      serviceTargetPort: Number(template.default_port || runtime.target),
      existingPvcName: "",
    },
  });

  useEffect(() => {
    form.setFocus("name", { shouldSelect: true });
  }, [form]);

  const submit = form.handleSubmit(
    (values) => {
      const [cpuRequest, cpuLimit] = values.cpu.split("|");
      const [memoryRequest, memoryLimit] = values.ram.split("|");
      createMutation.mutate({
        name: values.name,
        image: values.image,
        replicas: values.replicas,
        create_service: custom ? values.createService : true,
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
    },
    (errors) => {
      // Reveal the advanced section when the problem is hidden inside it.
      if (errors.image || errors.replicas || errors.servicePort || errors.serviceTargetPort || errors.serviceType) {
        setAdvancedOpen(true);
      }
    },
  );

  const errors = form.formState.errors;
  const watchedCpu = form.watch("cpu") || "";
  const watchedRam = form.watch("ram") || "";
  const watchedReplicas = form.watch("replicas") || 1;
  const watchedCreateService = form.watch("createService");
  const [cpuRequest, cpuLimit] = watchedCpu.split("|");
  const [memoryRequest, memoryLimit] = watchedRam.split("|");
  const selectedSize = sizes.find((size) => optionValue(size.cpu) === watchedCpu && optionValue(size.memory) === watchedRam)?.key;

  const projected = useMemo(() => {
    const replicas = custom ? watchedReplicas : 1;
    const pods = MULTI_POD_TYPES.includes(deploymentType) ? 2 : replicas;
    return {
      apps: 1,
      pods,
      cpuM: parseCpuMillicores(cpuRequest) * pods,
      memMi: parseMemoryMi(memoryRequest) * pods,
    };
  }, [cpuRequest, custom, deploymentType, memoryRequest, watchedReplicas]);

  const quotaOverages = useMemo(() => {
    if (!quotas) return [];
    const over: string[] = [];
    if (quotas.usage.apps_used + projected.apps > quotas.limits.max_apps) over.push(t("launch.quota_apps"));
    if (quotas.usage.cpu_m_used + projected.cpuM > quotas.limits.max_requests_cpu_m) over.push(t("launch.quota_cpu"));
    if (quotas.usage.mem_mi_used + projected.memMi > quotas.limits.max_requests_mem_mi) over.push(t("launch.quota_memory"));
    return over;
  }, [projected, quotas, t]);

  const resourceSummary = t("launch.resources_value", {
    cpu: cpuLabel(cpuRequest, locale),
    memory: memoryLabel(memoryRequest, locale),
  });

  return (
    <form className="form-grid" onSubmit={submit} noValidate>
      <Field id="launch-name" label={t("launch.name")} error={errors.name?.message} hint={t("launch.name_hint")} required>
        <input id="launch-name" autoComplete="off" spellCheck={false} {...form.register("name")} />
      </Field>

      {student ? (
        <div className="field full">
          <span className="text-[var(--text-sm)] font-medium text-[var(--text-soft)]">{t("launch.resources")}</span>
          <p className="m-0 flex items-center gap-2 text-[var(--text-sm)]">
            <Lock size={14} className="shrink-0 text-[var(--muted)]" aria-hidden="true" />
            <span>
              <strong>{resourceSummary}</strong>
              <span className="muted"> · {t("launch.student_policy")}</span>
            </span>
          </p>
        </div>
      ) : (
        <fieldset className="field full m-0 border-0 p-0">
          <legend className="mb-1.5 text-[var(--text-sm)] font-medium text-[var(--text-soft)]">{t("launch.size")}</legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {sizes.map((size) => {
              const checked = selectedSize === size.key;
              return (
                <label
                  key={size.key}
                  className={cn(
                    "flex cursor-pointer flex-col gap-0.5 rounded-[var(--radius)] border p-3 transition-colors has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-[var(--primary)]",
                    checked
                      ? "border-[var(--primary)] bg-[var(--surface-muted)]"
                      : "border-[var(--border)] hover:border-[var(--border-strong)]",
                  )}
                >
                  <input
                    type="radio"
                    name="launch-size"
                    className="sr-only"
                    checked={checked}
                    onChange={() => {
                      form.setValue("cpu", optionValue(size.cpu), { shouldDirty: true });
                      form.setValue("ram", optionValue(size.memory), { shouldDirty: true });
                    }}
                  />
                  <strong className="text-[var(--text-sm)]">{t(`launch.size_${size.key}`)}</strong>
                  <span className="muted text-[var(--text-xs)]">
                    {cpuLabel(size.cpu.request, locale)} · {memoryLabel(size.memory.request, locale)}
                  </span>
                  <span className="muted text-[var(--text-xs)]">{t(`launch.size_${size.key}_hint`)}</span>
                </label>
              );
            })}
          </div>
          {!selectedSize ? <span className="muted mt-1.5 block text-[var(--text-xs)]">{t("launch.size_custom", { value: resourceSummary })}</span> : null}
        </fieldset>
      )}

      {pvcSupported ? (
        <Field
          id="launch-volume"
          label={t("launch.volume")}
          hint={DESKTOP_TYPES.includes(deploymentType) ? t("launch.volume_hint_desktop") : t("launch.volume_hint")}
        >
          <select id="launch-volume" {...form.register("existingPvcName")}>
            <option value="">{t("launch.volume_new")}</option>
            {pvcs.map((pvc) => (
              <option value={pvc.name} key={pvc.name}>
                {[
                  pvc.name,
                  pvc.storage || t("launch.volume_unknown_size"),
                  pvc.bound ? t("launch.volume_in_use") : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      {hasAdvanced ? (
        <details
          className="field full rounded-[var(--radius)] border border-[var(--border)] px-3 py-2"
          open={advancedOpen}
          onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
        >
          <summary className="flex cursor-pointer list-none items-center gap-2 py-1 text-[var(--text-sm)] font-medium text-[var(--text-soft)] [&::-webkit-details-marker]:hidden">
            <ChevronRight size={15} className={cn("transition-transform", advancedOpen && "rotate-90")} aria-hidden="true" />
            {t("launch.advanced")}
            <span className="muted font-normal">· {t(custom ? "launch.advanced_hint_custom" : "launch.advanced_hint")}</span>
          </summary>
          <div className="form-grid pb-2 pt-3">
            {!student ? (
              <>
                <Field id="launch-cpu" label={t("launch.cpu")} half>
                  <select id="launch-cpu" {...form.register("cpu")}>
                    {cpuPresets.map((preset) => (
                      <option value={optionValue(preset)} key={optionValue(preset)}>
                        {cpuLabel(preset.request, locale)} ({preset.request} → {preset.limit})
                      </option>
                    ))}
                  </select>
                </Field>
                <Field id="launch-ram" label={t("launch.memory")} half>
                  <select id="launch-ram" {...form.register("ram")}>
                    {memoryPresets.map((preset) => (
                      <option value={optionValue(preset)} key={optionValue(preset)}>
                        {memoryLabel(preset.request, locale)} ({preset.request} → {preset.limit})
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            ) : null}

            {custom ? (
              <>
                <Field id="launch-image" label={t("launch.image")} error={errors.image?.message} required>
                  <input id="launch-image" spellCheck={false} {...form.register("image")} />
                </Field>
                {!student ? (
                  <Field id="launch-replicas" label={t("launch.replicas")} error={errors.replicas?.message} half>
                    <input id="launch-replicas" type="number" min={1} max={5} {...form.register("replicas", { valueAsNumber: true })} />
                  </Field>
                ) : null}
                <div className={cn("field", student && "full")}>
                  <span className="text-[var(--text-sm)] font-medium text-[var(--text-soft)]">{t("launch.network")}</span>
                  <label className="flex min-h-10 cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border)] px-2.5 text-[var(--text-sm)]">
                    <input type="checkbox" {...form.register("createService")} />
                    {t("launch.create_service")}
                  </label>
                </div>
                {watchedCreateService ? (
                  <>
                    <Field id="launch-service-type" label={t("launch.service_type")} half>
                      <select id="launch-service-type" {...form.register("serviceType")}>
                        {SERVICE_TYPES.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field id="launch-port" label={t("launch.service_port")} error={errors.servicePort?.message} half>
                      <input id="launch-port" type="number" {...form.register("servicePort", { valueAsNumber: true })} />
                    </Field>
                    <Field id="launch-target-port" label={t("launch.target_port")} error={errors.serviceTargetPort?.message} half>
                      <input id="launch-target-port" type="number" {...form.register("serviceTargetPort", { valueAsNumber: true })} />
                    </Field>
                  </>
                ) : null}
              </>
            ) : null}
          </div>
        </details>
      ) : null}

      <div className="field full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface-muted)] p-3.5">
        <strong className="flex items-center gap-2 text-[var(--text-sm)]">
          <Sparkles size={15} className="text-[var(--primary)]" aria-hidden="true" />
          {t("launch.summary_title")}
        </strong>
        <p className="muted m-0 text-[var(--text-xs)]">
          {projected.pods > 1
            ? t("launch.summary_pods", { pods: projected.pods, resources: resourceSummary })
            : t("launch.summary_one", { resources: resourceSummary })}
          {cpuLimit && memoryLimit ? ` ${t("launch.summary_limits", { cpu: cpuLabel(cpuLimit, locale), memory: memoryLabel(memoryLimit, locale) })}` : ""}
        </p>
        {quotas ? (
          <div className="grid gap-2 pt-2">
            <ResourceMeter label={t("launch.after_apps")} used={quotas.usage.apps_used + projected.apps} max={quotas.limits.max_apps} />
            <ResourceMeter label={t("launch.after_cpu")} used={quotas.usage.cpu_m_used + projected.cpuM} max={quotas.limits.max_requests_cpu_m} unit="m" />
            <ResourceMeter label={t("launch.after_memory")} used={quotas.usage.mem_mi_used + projected.memMi} max={quotas.limits.max_requests_mem_mi} unit="Mi" />
          </div>
        ) : null}
      </div>

      {quotaOverages.length ? (
        <div className="field full">
          <ErrorState title={t("launch.quota_title")}>
            {t("launch.quota_exceeded", { items: quotaOverages.join(", ") })} {t("launch.quota_hint")}
          </ErrorState>
        </div>
      ) : null}
      {createMutation.error ? (
        <div className="field full">
          <ErrorState title={t("launch.failed_title")}>
            {createMutation.error instanceof Error && createMutation.error.message ? createMutation.error.message : t("labs.unknown_error")}
          </ErrorState>
        </div>
      ) : null}

      <div className="actions-row field full justify-end">
        <Button type="button" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        <Button variant="primary" type="submit" disabled={createMutation.isPending || quotaOverages.length > 0}>
          {createMutation.isPending ? (
            <Loader2 size={16} className="animate-spin" aria-hidden="true" />
          ) : (
            <Rocket size={16} aria-hidden="true" />
          )}
          {createMutation.isPending ? t("launch.submitting") : t("launch.submit")}
        </Button>
      </div>
    </form>
  );
}

/** Form field whose label is tied to its control (`id`) and whose hint/error are announced. */
function Field({
  id,
  label,
  error,
  hint,
  required,
  half,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  half?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={cn("field", !half && "full")}>
      <label htmlFor={id}>
        {label}
        {required ? <span className="required"> *</span> : null}
      </label>
      {children}
      {error ? (
        <span className="text-[var(--text-xs)] font-medium text-[var(--danger)]" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span className="muted text-[var(--text-xs)]">{hint}</span>
      ) : null}
    </div>
  );
}
