import "../styles/main.css";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, Lock, ShieldCheck, User } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, Link } from "react-router-dom";
import { z } from "zod";
import { Button, ErrorState, LoadingState } from "../components/ui";
import { getCurrentUser, getSsoStatus, login } from "../lib/api";
import { useI18n } from "../lib/i18n";

const schema = z.object({
  username: z.string().min(1),
  password: z.string().min(1)
});

type LoginForm = z.infer<typeof schema>;

export default function LoginPage() {
  const navigate = useNavigate();
  const { locale, t } = useI18n();

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
      navigate("/");
    }
  });

  useEffect(() => {
    if (session.data) {
      navigate("/");
    }
  }, [session.data, navigate]);

  if (session.data) {
    return <LoadingState label={locale === "fr" ? "Session active" : "Active session"} />;
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
          <h1>{locale === "fr" ? "Accès direct à vos environnements pédagogiques." : "Direct access to your learning environments."}</h1>
          <p className="muted">{locale === "fr" ? "Une interface claire pour démarrer, pauser et retrouver vos labs Kubernetes." : "A clean interface to launch, pause, and restore your Kubernetes labs."}</p>
          <div className="auth-list">
            <span>{locale === "fr" ? "Templates contrôlés par rôle" : "Role-controlled templates"}</span>
            <span>{locale === "fr" ? "Volumes persistants visibles" : "Visible persistent volumes"}</span>
            <span>{locale === "fr" ? "Quotas et états de labs en temps réel" : "Real-time quotas and lab statuses"}</span>
          </div>
        </div>
        <span className="muted">© 2026 LabOnDemand</span>
      </section>

      <section className="auth-form-panel">
        <form className="card auth-card" onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
          <div>
            <h1>{t("login.title")}</h1>
            <p className="sub">{t("login.info")}</p>
          </div>
          {mutation.error ? <ErrorState title={t("login.error")}>{mutation.error.message}</ErrorState> : null}
          <div className="field">
            <label htmlFor="username">
              <User size={16} /> {t("login.username")}
            </label>
            <input id="username" autoComplete="username" {...form.register("username")} />
          </div>
          <div className="field">
            <label htmlFor="password">
              <Lock size={16} /> {t("login.password")}
            </label>
            <input id="password" type="password" autoComplete="current-password" {...form.register("password")} />
          </div>
          <Button className="btn-login" variant="primary" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? (locale === "fr" ? "Connexion..." : "Signing in...") : t("login.submit")}
            <ArrowRight size={16} />
          </Button>
          {sso.data ? (
            <Button type="button" onClick={() => (window.location.href = "/api/v1/auth/sso/login")}>
              <ShieldCheck size={16} />
              {t("login.sso_continue")}
            </Button>
          ) : (
            <p className="muted text-center">
              {locale === "fr" ? "Pas encore de compte ?" : "Don't have an account?"}{" "}
              <Link className="font-bold text-[var(--primary)]" to="/register">
                {locale === "fr" ? "S'inscrire" : "Register"}
              </Link>
            </p>
          )}
        </form>
      </section>
    </main>
  );
}
