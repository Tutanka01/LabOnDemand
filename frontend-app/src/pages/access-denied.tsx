import "../styles/main.css";
import { Lock } from "lucide-react";
import { createRoot } from "react-dom/client";
import { Button } from "../components/ui";

function AccessDenied() {
  return (
    <main className="auth-form-panel" style={{ minHeight: "100vh" }}>
      <section className="card auth-card">
        <Lock size={28} />
        <h1>Acces refuse</h1>
        <p className="sub">Votre role ne permet pas d'ouvrir cette page.</p>
        <Button id="back-to-home" variant="primary" onClick={() => (window.location.href = "index.html")}>
          Retour au dashboard
        </Button>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<AccessDenied />);
