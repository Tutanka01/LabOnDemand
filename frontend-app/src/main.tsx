import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryProvider } from "./lib/query";
import { I18nProvider } from "./lib/i18n";
import { applyTheme, getInitialTheme } from "./lib/theme";
import { cleanupLegacyServiceWorkers } from "./lib/serviceWorkerCleanup";
import { reloadForNewVersion } from "./components/ErrorBoundary";
import { AppRoutes } from "./routes";
import "./styles/main.css";

// Keep this entry chunk small: components/ui.tsx (Radix, TanStack Table) is
// only loaded with the pages that use it; the AppShell provides the tooltips.

// Apply the theme before the first render, public pages included.
applyTheme(getInitialTheme());
cleanupLegacyServiceWorkers();

// After a deployment, chunks referenced by an already open tab no longer exist:
// reload once to pick up the new index.html instead of failing the navigation.
window.addEventListener("vite:preloadError", (event) => {
  if (reloadForNewVersion()) event.preventDefault();
});

createRoot(document.getElementById("root")!).render(
  <QueryProvider>
    <I18nProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </I18nProvider>
  </QueryProvider>,
);
