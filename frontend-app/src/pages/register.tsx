import "../styles/main.css";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, ShieldCheck, UserPlus } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../components/ui";
import { getSsoStatus } from "../lib/api";
import { useI18n } from "../lib/i18n";

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
        <div className="card auth-card">
          <UserPlus size={28} />
          <div>
            <h1>{locale === "fr" ? "Inscription indisponible" : "Registration unavailable"}</h1>
            <p className="sub">
              {locale === "fr"
                ? "Demandez la création de votre compte à un administrateur LabOnDemand, ou connectez-vous via SSO si votre établissement l'a activé."
                : "Request your account creation from a LabOnDemand administrator, or sign in via SSO if your institution has enabled it."}
            </p>
          </div>

          {sso.data ? (
            <Button variant="primary" type="button" onClick={() => (window.location.href = "/api/v1/auth/sso/login")}>
              <ShieldCheck size={16} />
              {t("register.sso_managed") || "Continuer avec SSO"}
            </Button>
          ) : null}

          <Link to="/admin" className="w-full">
            <Button type="button" className="w-full">
              <UserPlus size={16} />
              {locale === "fr" ? "Espace administrateur" : "Administrator space"}
            </Button>
          </Link>

          <Link to="/login" className="w-full">
            <Button type="button" className="w-full">
              {t("register.login") || "Se connecter"}
              <ArrowRight size={16} />
            </Button>
          </Link>
        </div>
      </section>
    </main>
  );
}
