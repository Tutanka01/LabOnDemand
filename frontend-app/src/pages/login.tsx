import "../styles/main.css";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, Lock, ShieldCheck, User } from "lucide-react";
import { createRoot } from "react-dom/client";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, ErrorState, LoadingState } from "../components/ui";
import { getCurrentUser, getSsoStatus, login } from "../lib/api";
import { QueryProvider } from "../lib/query";

const schema = z.object({
  username: z.string().min(1),
  password: z.string().min(1)
});

type LoginForm = z.infer<typeof schema>;

function LoginPage() {
  const shouldCheckExistingSession = sessionStorage.getItem("user") !== null;
  const session = useQuery({
    queryKey: ["me"],
    queryFn: getCurrentUser,
    retry: false,
    enabled: shouldCheckExistingSession,
  });
  const sso = useQuery({ queryKey: ["sso"], queryFn: getSsoStatus });
  const form = useForm<LoginForm>({ resolver: zodResolver(schema), defaultValues: { username: "", password: "" } });
  const mutation = useMutation({
    mutationFn: (values: LoginForm) => login(values.username, values.password),
    onSuccess: (data) => {
      sessionStorage.setItem("user", JSON.stringify(data.user));
      window.location.href = "index.html";
    }
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
          <h1>Acces direct a vos environnements pedagogiques.</h1>
          <p className="muted">Une interface claire pour demarrer, pauser et retrouver vos labs Kubernetes.</p>
          <div className="auth-list">
            <span>Templates controles par role</span>
            <span>Volumes persistants visibles</span>
            <span>Quotas et etats de labs en temps reel</span>
          </div>
        </div>
        <span className="muted">© 2026 LabOnDemand</span>
      </section>

      <section className="auth-form-panel">
        <form className="card auth-card" onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
          <div>
            <h1>Connexion</h1>
            <p className="sub">Connectez-vous pour acceder a vos laboratoires.</p>
          </div>
          {mutation.error ? <ErrorState title="Connexion impossible">{mutation.error.message}</ErrorState> : null}
          <div className="field">
            <label htmlFor="username">
              <User size={16} /> Nom d'utilisateur
            </label>
            <input id="username" autoComplete="username" {...form.register("username")} />
          </div>
          <div className="field">
            <label htmlFor="password">
              <Lock size={16} /> Mot de passe
            </label>
            <input id="password" type="password" autoComplete="current-password" {...form.register("password")} />
          </div>
          <Button className="btn-login" variant="primary" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Connexion..." : "Se connecter"}
            <ArrowRight size={16} />
          </Button>
          {sso.data ? (
            <Button type="button" onClick={() => (window.location.href = "/api/v1/auth/sso/login")}>
              <ShieldCheck size={16} />
              Continuer avec SSO
            </Button>
          ) : (
            <p className="muted" style={{ textAlign: "center" }}>
              Pas encore de compte ? <a href="register.html" style={{ color: "var(--primary)", fontWeight: 700 }}>S'inscrire</a>
            </p>
          )}
        </form>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryProvider>
    <LoginPage />
  </QueryProvider>
);
