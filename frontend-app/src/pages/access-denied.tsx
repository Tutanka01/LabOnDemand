import "../styles/main.css";
import { ArrowLeft, LogIn, ShieldAlert } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../components/ui";
import { useI18n } from "../lib/i18n";

const stagger = (i: number) => ({
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] as const }
});

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
    <main className="grid min-h-screen place-items-center p-6">
      <motion.section
        {...stagger(0)}
        className="card auth-card text-center"
        style={{ boxShadow: "var(--shadow-lg)" }}
      >
        <motion.div
          {...stagger(1)}
          className="mx-auto grid h-14 w-14 place-items-center rounded-[var(--radius)]"
          style={{ background: "color-mix(in srgb, var(--danger) 10%, var(--surface))" }}
        >
          <ShieldAlert size={26} className="text-[var(--danger)]" />
        </motion.div>

        <motion.div {...stagger(2)} className="grid gap-2">
          <h1>
            {t("error.forbidden") || (locale === "fr" ? "Accès refusé" : "Access denied")}
          </h1>
          <p className="sub mx-auto max-w-[340px]">
            {locale === "fr"
              ? "Votre rôle ne permet pas d'ouvrir cette page."
              : "Your role does not allow you to open this page."}
          </p>
          {requiredRole ? (
            <span className="badge mx-auto">
              {locale === "fr" ? `Rôle requis : ${requiredRole}` : `Required role: ${requiredRole}`}
            </span>
          ) : null}
        </motion.div>

        <motion.div {...stagger(3)} className="grid gap-2">
          <Button id="back-to-home" className="w-full justify-center" variant="primary" onClick={() => navigate("/")}>
            <ArrowLeft size={16} />
            {locale === "fr" ? "Retour au dashboard" : "Back to dashboard"}
          </Button>
          <Button className="w-full justify-center" onClick={() => navigate("/login")}>
            <LogIn size={16} />
            {locale === "fr" ? "Changer de compte" : "Switch account"}
          </Button>
        </motion.div>

        <motion.span {...stagger(4)} className="muted text-xs">
          {locale === "fr" ? `Retour automatique dans ${countdown}s` : `Redirecting in ${countdown}s`}
        </motion.span>
      </motion.section>
    </main>
  );
}
