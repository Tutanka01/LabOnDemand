/**
 * Older releases shipped a caching service worker that could keep serving a
 * stale bundle. This unregisters any leftover registration, drops its caches
 * and reloads once if the current page was still controlled by it.
 * `public/sw.js` is the matching self-destructing worker for browsers that
 * fetch an update of the old registration before this code runs.
 */
export function cleanupLegacyServiceWorkers(): void {
  if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;

  const reloadKey = "labondemand-sw-cleanup-reloaded";

  void (async () => {
    const registrations = await navigator.serviceWorker.getRegistrations();
    if (registrations.length === 0) return;

    const wasControlled = Boolean(navigator.serviceWorker.controller);
    await Promise.all(registrations.map((registration) => registration.unregister()));
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
    }

    if (wasControlled && sessionStorage.getItem(reloadKey) !== "1") {
      sessionStorage.setItem(reloadKey, "1");
      window.location.reload();
    }
  })().catch(() => undefined);
}
