/* Retire les anciens service workers qui peuvent servir un vieux bundle. */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    Promise.all([
      self.registration.unregister(),
      caches.keys().then((keys) => Promise.all(keys.map((key) => caches.delete(key)))),
    ]).then(() => self.clients.claim()),
  );
});
