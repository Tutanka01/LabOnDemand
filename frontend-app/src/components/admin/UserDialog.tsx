import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { User } from "../../types/api";
import { registerUser, updateUser } from "../../lib/api";
import { Button, ErrorState, IconButton, showToast } from "../ui";

const schema = z.object({
  username: z.string().min(3, "Minimum 3 caracteres"),
  email: z.string().email("Email invalide").or(z.literal("")).optional(),
  full_name: z.string().optional(),
  password: z.string().min(12, "Minimum 12 caractères").or(z.literal("")).optional(),
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
      showToast("Utilisateur créé", "success");
      onOpenChange(false);
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
      showToast("Utilisateur mis à jour", "success");
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
              <h2>{isEdit ? "Modifier l'utilisateur" : "Nouvel utilisateur"}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          {mutation.error ? <ErrorState>{mutation.error.message}</ErrorState> : null}

          {ssoEnabled && !isEdit ? (
            <p className="muted mb-3">SSO est actif. Créez un compte local seulement si cet utilisateur ne doit pas passer par l'IdP.</p>
          ) : null}

          <form
            className="form-grid"
            onSubmit={form.handleSubmit((data) => {
              if (!isEdit && !data.password) {
                form.setError("password", { message: "Mot de passe requis pour un compte local" });
                return;
              }
              mutation.mutate(data);
            })}
          >
            <div className="field full">
              <label htmlFor="username">Nom d'utilisateur</label>
              <input id="username" disabled={isEdit} {...form.register("username")} />
              {form.formState.errors.username ? <span className="badge red">{form.formState.errors.username.message}</span> : null}
            </div>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" type="email" {...form.register("email")} />
            </div>
            <div className="field">
              <label htmlFor="full_name">Nom complet</label>
              <input id="full_name" {...form.register("full_name")} />
            </div>
            {!isEdit || !(user?.auth_provider === "oidc") ? (
              <div className="field">
                <label htmlFor="password">
                  Mot de passe {isEdit ? "(laisser vide pour conserver)" : ""}
                </label>
                <input id="password" type="password" {...form.register("password")} />
                {form.formState.errors.password ? <span className="badge red">{form.formState.errors.password.message}</span> : null}
              </div>
            ) : (
              <div className="field">
                <span className="muted">Utilisateur SSO - mot de passe géré par l'IdP</span>
              </div>
            )}
            <div className="field">
              <label htmlFor="role">Role</label>
              <select id="role" {...form.register("role")}>
                <option value="student">Étudiant</option>
                <option value="teacher">Enseignant</option>
                <option value="admin">Administrateur</option>
              </select>
            </div>
            <div className="field">
              <label className="flex items-center gap-2">
                <input type="checkbox" {...form.register("is_active")} />
                Actif
              </label>
            </div>
            <div className="actions-row field full justify-end">
              <Button type="button" onClick={() => onOpenChange(false)}>Annuler</Button>
              <Button variant="primary" type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Enregistrement..." : isEdit ? "Mettre à jour" : "Créer"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
