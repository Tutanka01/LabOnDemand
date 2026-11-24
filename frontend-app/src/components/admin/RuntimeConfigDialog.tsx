import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { RuntimeConfig } from "../../types/api";
import { createRuntimeConfig, updateRuntimeConfig } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button, ErrorState, ModalShell, showToast } from "../ui";
import { FieldError } from "./FieldError";

// Validation messages are translation keys, resolved with t() when displayed.
const schema = z.object({
  key: z.string().min(2, "admin.validation_min_2").max(50, "admin.validation_max_50"),
  default_image: z.string().min(1, "admin.validation_required"),
  target_port: z.number("admin.validation_port").min(1, "admin.validation_port").max(65535, "admin.validation_port"),
  default_service_type: z.enum(["ClusterIP", "NodePort", "LoadBalancer"]),
  allowed_for_students: z.boolean(),
  min_cpu_request: z.string(),
  min_memory_request: z.string(),
  min_cpu_limit: z.string(),
  min_memory_limit: z.string(),
  active: z.boolean(),
});

type FormData = z.infer<typeof schema>;

const SERVICE_TYPES = ["ClusterIP", "NodePort", "LoadBalancer"] as const;

const RESOURCE_FIELDS = [
  { name: "min_cpu_request", label: "admin.field_cpu_request" },
  { name: "min_memory_request", label: "admin.field_memory_request" },
  { name: "min_cpu_limit", label: "admin.field_cpu_limit" },
  { name: "min_memory_limit", label: "admin.field_memory_limit" },
] as const;

export function RuntimeConfigDialog({
  config,
  open,
  onOpenChange,
}: {
  config?: RuntimeConfig | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
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
  const errors = form.formState.errors;

  const close = () => {
    form.reset();
    createMut.reset();
    updateMut.reset();
    onOpenChange(false);
  };

  const onSaved = (message: string) => {
    queryClient.invalidateQueries({ queryKey: ["runtime-configs"] });
    queryClient.invalidateQueries({ queryKey: ["templates"] });
    queryClient.invalidateQueries({ queryKey: ["resource-presets"] });
    showToast(message, "success");
    close();
  };

  const createMut = useMutation({
    mutationFn: (data: FormData) => createRuntimeConfig(data),
    onSuccess: () => onSaved(t("admin.toast_runtime_created")),
  });

  const updateMut = useMutation({
    mutationFn: (data: FormData) => updateRuntimeConfig(config!.id, data),
    onSuccess: () => onSaved(t("admin.toast_runtime_updated")),
  });

  const mutation = isEdit ? updateMut : createMut;

  return (
    <ModalShell
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(true) : close())}
      title={isEdit ? t("admin.edit_runtime") : t("admin.new_runtime_title")}
      wide
    >
      {mutation.error ? <ErrorState title={t("admin.error_save_runtime")} error={mutation.error} /> : null}

      <form className="form-grid" noValidate onSubmit={form.handleSubmit((data) => mutation.mutate(data))}>
        <div className="field">
          <label htmlFor="rc-key">
            {t("admin.col_key")}
            <span className="required"> *</span>
          </label>
          <input id="rc-key" {...form.register("key")} disabled={isEdit} aria-invalid={Boolean(errors.key)} />
          <FieldError message={errors.key?.message} />
        </div>
        <div className="field">
          <label htmlFor="rc-image">
            {t("admin.col_image")}
            <span className="required"> *</span>
          </label>
          <input id="rc-image" {...form.register("default_image")} aria-invalid={Boolean(errors.default_image)} />
          <FieldError message={errors.default_image?.message} />
        </div>
        <div className="field">
          <label htmlFor="rc-port">{t("admin.field_target_port")}</label>
          <input
            id="rc-port"
            type="number"
            {...form.register("target_port", { valueAsNumber: true })}
            aria-invalid={Boolean(errors.target_port)}
          />
          <FieldError message={errors.target_port?.message} />
        </div>
        <div className="field">
          <label htmlFor="rc-service">{t("admin.field_service_type")}</label>
          <select id="rc-service" {...form.register("default_service_type")}>
            {SERVICE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        {RESOURCE_FIELDS.map((field) => (
          <div className="field" key={field.name}>
            <label htmlFor={`rc-${field.name}`}>{t(field.label)}</label>
            <input id={`rc-${field.name}`} {...form.register(field.name)} />
          </div>
        ))}
        <div className="field">
          <label className="flex items-center gap-2">
            <input type="checkbox" {...form.register("allowed_for_students")} />
            {t("admin.field_allowed_for_students")}
          </label>
        </div>
        <div className="field">
          <label className="flex items-center gap-2">
            <input type="checkbox" {...form.register("active")} />
            {t("admin.col_active")}
          </label>
        </div>
        <div className="actions-row field full justify-end">
          <Button type="button" onClick={close}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? t("assignment.saving") : isEdit ? t("assignment.update") : t("admin.create")}
          </Button>
        </div>
      </form>
    </ModalShell>
  );
}
