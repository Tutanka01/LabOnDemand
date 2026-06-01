export function cleanupLegacyServiceWorkers(): void {
  if (typeof window === "undefined") return;

  const reloadKey = "labondemand-sw-cleanup-reloaded";

  void (async () => {
    const hadController = Boolean(navigator.serviceWorker?.controller);
    let hadRegistrations = false;
    let hadCaches = false;

    if ("serviceWorker" in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      hadRegistrations = registrations.length > 0;
      await Promise.all(registrations.map((registration) => registration.unregister()));
    }

    if ("caches" in window) {
      const keys = await caches.keys();
      hadCaches = keys.length > 0;
      await Promise.all(keys.map((key) => caches.delete(key)));
    }

    if ((hadController || hadRegistrations || hadCaches) && sessionStorage.getItem(reloadKey) !== "1") {
      sessionStorage.setItem(reloadKey, "1");
      window.location.reload();
    }
  })().catch(() => undefined);
}
