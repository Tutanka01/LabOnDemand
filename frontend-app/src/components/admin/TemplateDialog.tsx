import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { Template } from "../../types/api";
import { createTemplate, updateTemplate } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button, ErrorState, ModalShell, showToast } from "../ui";
import { FieldError } from "./FieldError";

// Validation messages are translation keys, resolved with t() when displayed.
const schema = z.object({
  key: z.string().min(2, "admin.validation_min_2").max(50, "admin.validation_max_50"),
  name: z.string().min(2, "admin.validation_min_2").max(100, "admin.validation_max_100"),
  description: z.string().max(255, "admin.validation_max_255").optional(),
  icon: z.string().max(100, "admin.validation_max_100").optional(),
  deployment_type: z.string().regex(/^[a-z0-9][a-z0-9-]*$/, "admin.validation_slug"),
  default_image: z.string(),
  default_port: z.number("admin.validation_port").min(1, "admin.validation_port").max(65535, "admin.validation_port"),
  default_service_type: z.enum(["ClusterIP", "NodePort", "LoadBalancer"]),
  tags: z.string().optional(),
  active: z.boolean(),
});

type FormData = z.infer<typeof schema>;

const SERVICE_TYPES = ["ClusterIP", "NodePort", "LoadBalancer"] as const;

const toPayload = (data: FormData) => ({
  ...data,
  tags: data.tags ? data.tags.split(",").map((tag) => tag.trim()).filter(Boolean) : [],
  default_port: data.default_port,
});

export function TemplateDialog({
  template,
  open,
  onOpenChange,
}: {
  template?: Template | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
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
  const errors = form.formState.errors;

  const close = () => {
    form.reset();
    createMut.reset();
    updateMut.reset();
    onOpenChange(false);
  };

  const onSaved = (message: string) => {
    queryClient.invalidateQueries({ queryKey: ["templates-all"] });
    queryClient.invalidateQueries({ queryKey: ["templates"] });
    showToast(message, "success");
    close();
  };

  const createMut = useMutation({
    mutationFn: (data: FormData) => createTemplate(toPayload(data)),
    onSuccess: () => onSaved(t("admin.toast_template_created")),
  });

  const updateMut = useMutation({
    mutationFn: (data: FormData) => updateTemplate(template!.id!, toPayload(data)),
    onSuccess: () => onSaved(t("admin.toast_template_updated")),
  });

  const mutation = isEdit ? updateMut : createMut;

  return (
    <ModalShell
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(true) : close())}
      title={isEdit ? t("admin.edit_template") : t("admin.new_template")}
    >
      {mutation.error ? <ErrorState title={t("admin.error_save_template")} error={mutation.error} /> : null}

      <form className="form-grid" noValidate onSubmit={form.handleSubmit((data) => mutation.mutate(data))}>
        <div className="field">
          <label htmlFor="tpl-key">
            {t("admin.col_key")}
            <span className="required"> *</span>
          </label>
          <input id="tpl-key" {...form.register("key")} disabled={isEdit} aria-invalid={Boolean(errors.key)} />
          <FieldError message={errors.key?.message} />
        </div>
        <div className="field">
          <label htmlFor="tpl-name">
            {t("admin.col_name")}
            <span className="required"> *</span>
          </label>
          <input id="tpl-name" {...form.register("name")} aria-invalid={Boolean(errors.name)} />
          <FieldError message={errors.name?.message} />
        </div>
        <div className="field full">
          <label htmlFor="tpl-description">{t("admin.field_description")}</label>
          <input id="tpl-description" {...form.register("description")} />
          <FieldError message={errors.description?.message} />
        </div>
        <div className="field">
          <label htmlFor="tpl-icon">{t("admin.field_icon")}</label>
          <input id="tpl-icon" {...form.register("icon")} />
          <FieldError message={errors.icon?.message} />
        </div>
        <div className="field">
          <label htmlFor="tpl-type">{t("admin.field_deployment_type")}</label>
          <input
            id="tpl-type"
            {...form.register("deployment_type")}
            placeholder="custom, vscode, jupyter..."
            aria-invalid={Boolean(errors.deployment_type)}
          />
          <FieldError message={errors.deployment_type?.message} />
        </div>
        <div className="field">
          <label htmlFor="tpl-image">{t("admin.field_default_image")}</label>
          <input id="tpl-image" {...form.register("default_image")} />
        </div>
        <div className="field">
          <label htmlFor="tpl-port">{t("admin.field_default_port")}</label>
          <input
            id="tpl-port"
            type="number"
            {...form.register("default_port", { valueAsNumber: true })}
            aria-invalid={Boolean(errors.default_port)}
          />
          <FieldError message={errors.default_port?.message} />
        </div>
        <div className="field">
          <label htmlFor="tpl-service">{t("admin.field_service_type")}</label>
          <select id="tpl-service" {...form.register("default_service_type")}>
            {SERVICE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        <div className="field full">
          <label htmlFor="tpl-tags">{t("admin.field_tags")}</label>
          <input id="tpl-tags" {...form.register("tags")} />
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
