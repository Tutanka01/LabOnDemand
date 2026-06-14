import "../styles/main.css";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, ShieldCheck, UserPlus } from "lucide-react";
import { motion } from "motion/react";
import { Link } from "react-router-dom";
import { Button } from "../components/ui";
import { getSsoStatus } from "../lib/api";
import { useI18n } from "../lib/i18n";

const stagger = (i: number) => ({
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] as const }
});

export default function RegisterPage() {
  const { locale, t } = useI18n();
  const sso = useQuery({ queryKey: ["sso"], queryFn: getSsoStatus });

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
          <h1>{t("register.title")}</h1>
          <p className="muted">
            {locale === "fr"
              ? "Création de compte contrôlée. Les comptes locaux sont créés par un administrateur. Quand le SSO est actif, utilisez votre fournisseur d'identité institutionnel."
              : "Controlled account creation. Local accounts are created by an administrator. When SSO is active, use your institutional identity provider."}
          </p>
          <div className="auth-list">
            <span>{locale === "fr" ? "Rôles et quotas validés avant activation" : "Roles and quotas validated before activation"}</span>
            <span>{locale === "fr" ? "Comptes SSO rattachés automatiquement" : "SSO accounts linked automatically"}</span>
            <span>{locale === "fr" ? "Création locale réservée à l'administration" : "Local creation restricted to administration"}</span>
          </div>
        </div>
        <span className="muted">© 2026 LabOnDemand</span>
      </section>

      <section className="auth-form-panel">
        <div className="card auth-card text-center">
          <motion.div
            {...stagger(0)}
            className="mx-auto grid h-14 w-14 place-items-center rounded-2xl text-white"
            style={{
              background: "var(--gradient-brand)",
              boxShadow: "0 10px 28px -10px color-mix(in srgb, var(--primary) 75%, transparent)"
            }}
          >
            <UserPlus size={26} />
          </motion.div>

          <motion.div {...stagger(1)} className="grid gap-1.5">
            <h1
              className="text-[1.55rem] font-bold leading-tight tracking-[-0.02em]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {locale === "fr" ? "Inscription indisponible" : "Registration unavailable"}
            </h1>
            <p className="sub">
              {locale === "fr"
                ? "Demandez la création de votre compte à un administrateur LabOnDemand, ou connectez-vous via SSO si votre établissement l'a activé."
                : "Request your account creation from a LabOnDemand administrator, or sign in via SSO if your institution has enabled it."}
            </p>
          </motion.div>

          {sso.data ? (
            <motion.div {...stagger(2)}>
              <Button className="w-full justify-center" variant="primary" type="button" onClick={() => (window.location.href = "/api/v1/auth/sso/login")}>
                <ShieldCheck size={16} />
                {t("register.sso_managed") || (locale === "fr" ? "Continuer avec SSO" : "Continue with SSO")}
              </Button>
            </motion.div>
          ) : null}

          <motion.div {...stagger(3)} className="grid gap-2.5">
            <Link to="/admin" className="w-full">
              <Button type="button" className="w-full justify-center">
                <UserPlus size={16} />
                {locale === "fr" ? "Espace administrateur" : "Administrator space"}
              </Button>
            </Link>

            <Link to="/login" className="w-full">
              <Button type="button" className="w-full justify-center">
                {t("register.login") || (locale === "fr" ? "Se connecter" : "Sign in")}
                <ArrowRight size={16} />
              </Button>
            </Link>
          </motion.div>
        </div>
      </section>
    </main>
  );
}
