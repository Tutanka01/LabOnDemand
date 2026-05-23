import "../styles/main.css";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, ShieldCheck, UserPlus } from "lucide-react";
import { createRoot } from "react-dom/client";
import { Button } from "../components/ui";
import { getSsoStatus } from "../lib/api";
import { QueryProvider } from "../lib/query";

function RegisterPage() {
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
          <h1>Creation de compte controlee.</h1>
          <p className="muted">
            Les comptes locaux sont crees par un administrateur. Quand le SSO est actif, utilisez votre fournisseur
            d'identite institutionnel.
          </p>
          <div className="auth-list">
            <span>Roles et quotas valides avant activation</span>
            <span>Comptes SSO rattaches automatiquement</span>
            <span>Creation locale reservee a l'administration</span>
          </div>
        </div>
        <span className="muted">© 2026 LabOnDemand</span>
      </section>

      <section className="auth-form-panel">
        <div className="card auth-card">
          <UserPlus size={28} />
          <div>
            <h1>Inscription indisponible</h1>
            <p className="sub">
              Demandez la creation de votre compte a un administrateur LabOnDemand, ou connectez-vous via SSO si votre
              etablissement l'a active.
            </p>
          </div>

          {sso.data ? (
            <Button variant="primary" type="button" onClick={() => (window.location.href = "/api/v1/auth/sso/login")}>
              <ShieldCheck size={16} />
              Continuer avec SSO
            </Button>
          ) : null}

          <Button type="button" onClick={() => (window.location.href = "admin.html#users")}>
            <UserPlus size={16} />
            Espace administrateur
          </Button>

          <Button type="button" onClick={() => (window.location.href = "login.html")}>
            Se connecter
            <ArrowRight size={16} />
          </Button>
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryProvider>
    <RegisterPage />
  </QueryProvider>,
);
