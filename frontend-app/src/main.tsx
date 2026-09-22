import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryProvider } from "./lib/query";
import { I18nProvider } from "./lib/i18n";
import { applyTheme, getInitialTheme } from "./lib/theme";
import { AppRoutes } from "./routes";
import { TooltipProvider } from "./components/ui";
import "./styles/main.css";

// Le thème s'applique dès le démarrage, y compris sur les pages publiques.
applyTheme(getInitialTheme());

createRoot(document.getElementById("root")!).render(
  <QueryProvider>
    <I18nProvider>
      {/* Radix exige un Provider au-dessus de tout Tooltip.Root. */}
      <TooltipProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </TooltipProvider>
    </I18nProvider>
  </QueryProvider>
);
