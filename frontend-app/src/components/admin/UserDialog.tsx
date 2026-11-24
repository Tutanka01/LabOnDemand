import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { User } from "../../types/api";
import { registerUser, updateUser } from "../../lib/api";
import { roleLabel } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { Button, ErrorState, ModalShell, showToast } from "../ui";
import { FieldError } from "./FieldError";

// Validation messages are translation keys, resolved with t() when displayed.
const schema = z.object({
  username: z.string().min(3, "admin.validation_min_3"),
  email: z.string().email("admin.validation_email").or(z.literal("")).optional(),
  full_name: z.string().optional(),
  password: z.string().min(12, "admin.validation_password_12").or(z.literal("")).optional(),
  role: z.enum(["student", "teacher", "admin"]),
  is_active: z.boolean(),
});

type FormData = z.infer<typeof schema>;

export function UserDialog({
  user,
  ssoEnabled,
  open,
  onOpenChange,
}: {
  user?: User | null;
  ssoEnabled: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { locale, t } = useI18n();
  const queryClient = useQueryClient();
  const isEdit = Boolean(user);

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      username: user?.username || "",
      email: user?.email || "",
      full_name: user?.full_name || "",
      password: "",
      role: user?.role || "student",
      is_active: user?.is_active !== false,
    },
  });
  const errors = form.formState.errors;

  const close = () => {
    form.reset();
    createMut.reset();
    updateMut.reset();
    onOpenChange(false);
  };

  const createMut = useMutation({
    mutationFn: (data: FormData) =>
      registerUser({
        username: data.username,
        email: data.email || "",
        full_name: data.full_name,
        password: data.password || "",
        role: data.role,
        is_active: data.is_active,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      showToast(t("admin.toast_user_created"), "success");
      close();
    },
  });

  const updateMut = useMutation({
    mutationFn: (data: Partial<FormData>) => {
      const payload: Record<string, unknown> = {};
      if (data.email !== undefined) payload.email = data.email;
      if (data.full_name !== undefined) payload.full_name = data.full_name;
      if (data.role !== undefined) payload.role = data.role;
      if (data.is_active !== undefined) payload.is_active = data.is_active;
      if (data.password && data.password.length >= 8) payload.password = data.password;
      return updateUser(user!.id, payload as Partial<User & { password: string }>);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      showToast(t("admin.toast_user_updated"), "success");
      close();
    },
  });

  const mutation = isEdit ? updateMut : createMut;
  const ssoUser = isEdit && user?.auth_provider === "oidc";

  return (
    <ModalShell
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(true) : close())}
      title={isEdit ? t("admin.edit_user") : t("admin.new_user_title")}
    >
      {mutation.error ? <ErrorState title={t("admin.error_save_user")} error={mutation.error} /> : null}

      {ssoEnabled && !isEdit ? <p className="muted mb-3">{t("admin.sso_local_account_hint")}</p> : null}

      <form
        className="form-grid"
        noValidate
        onSubmit={form.handleSubmit((data) => {
          if (!isEdit && !data.password) {
            form.setError("password", { message: "admin.validation_password_required" });
            return;
          }
          mutation.mutate(data);
        })}
      >
        <div className="field full">
          <label htmlFor="user-username">
            {t("students.username")}
            <span className="required"> *</span>
          </label>
          <input
            id="user-username"
            disabled={isEdit}
            autoComplete="off"
            aria-invalid={Boolean(errors.username)}
            {...form.register("username")}
          />
          <FieldError message={errors.username?.message} />
        </div>
        <div className="field">
          <label htmlFor="user-email">{t("students.email")}</label>
          <input id="user-email" type="email" aria-invalid={Boolean(errors.email)} {...form.register("email")} />
          <FieldError message={errors.email?.message} />
        </div>
        <div className="field">
          <label htmlFor="user-full-name">{t("teacher.full_name")}</label>
          <input id="user-full-name" {...form.register("full_name")} />
        </div>
        {!ssoUser ? (
          <div className="field">
            <label htmlFor="user-password">
              {t("login.password")}
              {isEdit ? ` ${t("admin.password_keep_hint")}` : <span className="required"> *</span>}
            </label>
            <input
              id="user-password"
              type="password"
              autoComplete="new-password"
              aria-invalid={Boolean(errors.password)}
              {...form.register("password")}
            />
            <FieldError message={errors.password?.message} />
          </div>
        ) : (
          <div className="field">
            <span className="muted">{t("admin.sso_password_managed")}</span>
          </div>
        )}
        <div className="field">
          <label htmlFor="user-role">{t("admin.col_role")}</label>
          <select id="user-role" {...form.register("role")}>
            <option value="student">{roleLabel("student", locale)}</option>
            <option value="teacher">{roleLabel("teacher", locale)}</option>
            <option value="admin">{roleLabel("admin", locale)}</option>
          </select>
        </div>
        <div className="field">
          <label className="flex items-center gap-2">
            <input type="checkbox" {...form.register("is_active")} />
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
