import "../styles/main.css";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, Lock, Mail, ShieldCheck, User } from "lucide-react";
import { createRoot } from "react-dom/client";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, ErrorState, LoadingState } from "../components/ui";
import { getCurrentUser, getSsoStatus, registerUser } from "../lib/api";
import { QueryProvider } from "../lib/query";

const schema = z.object({
  username: z.string().min(3, "Minimum 3 caracteres"),
  email: z.string().email("Email invalide"),
  full_name: z.string().optional(),
  password: z.string().min(8, "Minimum 8 caracteres"),
  confirmPassword: z.string(),
}).refine((d) => d.password === d.confirmPassword, {
  message: "Les mots de passe ne correspondent pas",
  path: ["confirmPassword"],
});

type RegisterForm = z.infer<typeof schema>;

function RegisterPage() {
  const session = useQuery({ queryKey: ["me"], queryFn: getCurrentUser, retry: false });
  const sso = useQuery({ queryKey: ["sso"], queryFn: getSsoStatus });
  const form = useForm<RegisterForm>({
    resolver: zodResolver(schema),
    defaultValues: { username: "", email: "", full_name: "", password: "", confirmPassword: "" },
  });

  const mutation = useMutation({
    mutationFn: (values: RegisterForm) =>
      registerUser({
        username: values.username,
        email: values.email,
        full_name: values.full_name,
        password: values.password,
      }),
    onSuccess: () => {
      setTimeout(() => {
        window.location.href = "login.html";
      }, 2000);
    },
  });

  if (session.data) {
    window.location.href = "index.html";
    return <LoadingState label="Session active" />;
  }

  return (
    <main className="auth-page">
      <section className="auth-brand">
        <div className="brand">
          <span className="brand-mark">
            <FlaskConical size={19} />
          </span>
          <span>LabOnDemand</span>
        </div>
        <div className="auth-copy">
          <h1>Creez votre compte pedagogique.</h1>
          <p className="muted">
            Rejoignez la plateforme pour deployer vos environnements de TP Kubernetes sans connaissance prealable.
          </p>
          <div className="auth-list">
            <span>Acces aux templates approuves</span>
            <span>Volumes persistants inclus</span>
            <span>Monitoring des quotas en temps reel</span>
          </div>
        </div>
        <span className="muted">© 2026 LabOnDemand</span>
      </section>

      <section className="auth-form-panel">
        <form className="card auth-card" onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
          <div>
            <h1>Inscription</h1>
            <p className="sub">
              {sso.data
                ? "L'authentification SSO est activee. Vous serez redirige vers votre fournisseur d'identite."
                : "Creez votre compte pour acceder aux laboratoires."}
            </p>
          </div>

          {mutation.isSuccess ? (
            <div className="empty-state" style={{ borderColor: "#bfe5d0", background: "#f1fbf5", color: "var(--green)" }}>
              <strong>Compte cree avec succes !</strong>
              <span>Redirection vers la page de connexion...</span>
            </div>
          ) : null}

          {mutation.error ? <ErrorState title="Inscription impossible">{mutation.error.message}</ErrorState> : null}

          {sso.data ? (
            <Button type="button" onClick={() => (window.location.href = "/api/v1/auth/sso/login")}>
              <ShieldCheck size={16} />
              Continuer avec SSO
            </Button>
          ) : (
            <>
              <div className="field">
                <label htmlFor="username">
                  <User size={16} /> Nom d'utilisateur
                </label>
                <input id="username" autoComplete="username" {...form.register("username")} />
                {form.formState.errors.username ? <span className="badge red">{form.formState.errors.username.message}</span> : null}
              </div>
              <div className="field">
                <label htmlFor="email">
                  <Mail size={16} /> Email
                </label>
                <input id="email" type="email" autoComplete="email" {...form.register("email")} />
                {form.formState.errors.email ? <span className="badge red">{form.formState.errors.email.message}</span> : null}
              </div>
              <div className="field">
                <label htmlFor="full_name">
                  <User size={16} /> Nom complet (optionnel)
                </label>
                <input id="full_name" autoComplete="name" {...form.register("full_name")} />
              </div>
              <div className="field">
                <label htmlFor="password">
                  <Lock size={16} /> Mot de passe
                </label>
                <input id="password" type="password" autoComplete="new-password" {...form.register("password")} />
                {form.formState.errors.password ? <span className="badge red">{form.formState.errors.password.message}</span> : null}
              </div>
              <div className="field">
                <label htmlFor="confirmPassword">
                  <Lock size={16} /> Confirmer le mot de passe
                </label>
                <input id="confirmPassword" type="password" {...form.register("confirmPassword")} />
                {form.formState.errors.confirmPassword ? <span className="badge red">{form.formState.errors.confirmPassword.message}</span> : null}
              </div>
              <Button className="btn-login" variant="primary" type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Creation..." : "Creer le compte"}
                <ArrowRight size={16} />
              </Button>
            </>
          )}

          <p className="muted" style={{ textAlign: "center" }}>
            Deja un compte ? <a href="login.html" style={{ color: "var(--primary)", fontWeight: 700 }}>Se connecter</a>
          </p>
        </form>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryProvider>
    <RegisterPage />
  </QueryProvider>,
);
