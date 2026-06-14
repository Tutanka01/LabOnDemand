import "../styles/main.css";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, Lock, ShieldCheck, User } from "lucide-react";
import { motion } from "motion/react";
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

const stagger = (i: number) => ({
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] as const }
});

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
          <motion.div {...stagger(0)} className="grid gap-1.5">
            <h1
              className="text-[1.7rem] font-bold leading-tight tracking-[-0.02em]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {t("login.title")}
            </h1>
            <p className="sub">{t("login.info")}</p>
          </motion.div>

          {mutation.error ? (
            <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
              <ErrorState title={t("login.error")}>{mutation.error.message}</ErrorState>
            </motion.div>
          ) : null}

          <motion.div {...stagger(1)} className="field">
            <label htmlFor="username">
              <span className="inline-flex items-center gap-2">
                <User size={15} className="text-[var(--muted)]" /> {t("login.username")}
              </span>
            </label>
            <input id="username" autoComplete="username" placeholder={locale === "fr" ? "votre identifiant" : "your username"} {...form.register("username")} />
          </motion.div>

          <motion.div {...stagger(2)} className="field">
            <label htmlFor="password">
              <span className="inline-flex items-center gap-2">
                <Lock size={15} className="text-[var(--muted)]" /> {t("login.password")}
              </span>
            </label>
            <input id="password" type="password" autoComplete="current-password" placeholder="••••••••" {...form.register("password")} />
          </motion.div>

          <motion.div {...stagger(3)}>
            <Button className="btn-login w-full justify-center" variant="primary" type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? (locale === "fr" ? "Connexion..." : "Signing in...") : t("login.submit")}
              <ArrowRight size={16} />
            </Button>
          </motion.div>

          {sso.data ? (
            <motion.div {...stagger(4)} className="grid gap-4">
              <div className="flex items-center gap-3 text-[0.78rem] font-medium uppercase tracking-wide text-[var(--muted)]">
                <span className="hairline h-px flex-1" />
                {locale === "fr" ? "ou" : "or"}
                <span className="hairline h-px flex-1" />
              </div>
              <Button className="w-full justify-center" type="button" onClick={() => (window.location.href = "/api/v1/auth/sso/login")}>
                <ShieldCheck size={16} />
                {t("login.sso_continue")}
              </Button>
            </motion.div>
          ) : (
            <motion.p {...stagger(4)} className="muted text-center">
              {locale === "fr" ? "Pas encore de compte ?" : "Don't have an account?"}{" "}
              <Link className="font-bold text-[var(--primary)] hover:underline" to="/register">
                {locale === "fr" ? "S'inscrire" : "Register"}
              </Link>
            </motion.p>
          )}
        </form>
      </section>
    </main>
  );
}
