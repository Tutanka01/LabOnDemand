import "../styles/main.css";
import { LogIn, Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../components/ui";
import { useI18n } from "../lib/i18n";

export default function AccessDeniedPage() {
  const navigate = useNavigate();
  const { locale, t } = useI18n();
  const [searchParams] = useSearchParams();
  const requiredRole = searchParams.get("role");
  const [countdown, setCountdown] = useState(8);

  useEffect(() => {
    const timer = window.setInterval(() => setCountdown((value) => Math.max(value - 1, 0)), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (countdown === 0) navigate("/");
  }, [countdown, navigate]);

  return (
    <main className="auth-form-panel min-h-screen">
      <section className="card auth-card">
        <Lock size={28} />
        <h1>{t("error.forbidden") || "Accès refusé"}</h1>
        <p className="sub">
          {locale === "fr" 
            ? `Votre rôle ne permet pas d'ouvrir cette page${requiredRole ? `; rôle requis: ${requiredRole}.` : "."}`
            : `Your role does not allow you to open this page${requiredRole ? `; required role: ${requiredRole}.` : "."}`}
        </p>
        <span className="badge blue">
          {locale === "fr" 
            ? `Retour automatique dans ${countdown}s` 
            : `Redirecting in ${countdown}s`}
        </span>
        <Button id="back-to-home" variant="primary" onClick={() => navigate("/")}>
          {locale === "fr" ? "Retour au dashboard" : "Back to dashboard"}
        </Button>
        <Button onClick={() => navigate("/login")}>
          <LogIn size={16} />
          {locale === "fr" ? "Changer de compte" : "Switch account"}
        </Button>
      </section>
    </main>
  );
}
