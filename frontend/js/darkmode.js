/**
 * darkmode.js — Bascule mode sombre / clair
 *
 * - Applique data-theme="dark"|"light" sur <html>
 * - Persiste le choix dans localStorage (clé: "labondemand-theme")
 * - Respecte prefers-color-scheme si aucune préférence stockée
 * - Expose window.toggleDarkMode() et window.initDarkMode()
 */

const STORAGE_KEY = "labondemand-theme";

function getPreferredTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return "light"; // Le mode clair est le mode par défaut
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  // Mettre à jour toutes les icônes de bascule présentes sur la page
  document.querySelectorAll(".dark-mode-toggle").forEach((btn) => {
    const isDark = theme === "dark";
    btn.title = isDark ? "Passer en mode clair" : "Passer en mode sombre";
    btn.setAttribute("aria-label", btn.title);
    // Met à jour l'icône FontAwesome ou l'emoji selon ce qui est dans le bouton
    const icon = btn.querySelector("i");
    if (icon) {
      icon.className = isDark ? "fas fa-sun" : "fas fa-moon";
    } else {
      btn.textContent = isDark ? "☀️" : "🌙";
    }
  });
}

function toggleDarkMode() {
  const current = document.documentElement.getAttribute("data-theme") || getPreferredTheme();
  const next = current === "dark" ? "light" : "dark";
  localStorage.setItem(STORAGE_KEY, next);
  applyTheme(next);
}

function initDarkMode() {
  const theme = getPreferredTheme();
  applyTheme(theme);

  // Ne pas écouter les changements système — le choix utilisateur prime toujours
}

// Initialisation immédiate pour éviter le flash blanc
initDarkMode();

window.toggleDarkMode = toggleDarkMode;
window.initDarkMode = initDarkMode;
