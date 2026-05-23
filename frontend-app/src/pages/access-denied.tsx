import "../styles/main.css";
import { LogIn, Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button } from "../components/ui";

function AccessDenied() {
  const [countdown, setCountdown] = useState(8);
  const params = new URLSearchParams(window.location.search);
  const requiredRole = params.get("role");

  useEffect(() => {
    const timer = window.setInterval(() => setCountdown((value) => Math.max(value - 1, 0)), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (countdown === 0) window.location.href = "index.html";
  }, [countdown]);

  return (
    <main className="auth-form-panel" style={{ minHeight: "100vh" }}>
      <section className="card auth-card">
        <Lock size={28} />
        <h1>Acces refuse</h1>
        <p className="sub">
          Votre role ne permet pas d'ouvrir cette page
          {requiredRole ? `; role requis: ${requiredRole}.` : "."}
        </p>
        <span className="badge blue">Retour automatique dans {countdown}s</span>
        <Button id="back-to-home" variant="primary" onClick={() => (window.location.href = "index.html")}>
          Retour au dashboard
        </Button>
        <Button onClick={() => (window.location.href = "login.html")}>
          <LogIn size={16} />
          Changer de compte
        </Button>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<AccessDenied />);
