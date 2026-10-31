// Sube CACHE a v3, v4, etc. cada vez que cambien los assets precacheados o su estrategia.
const CACHE = "mi-tie-lista-v2";
const SHELL = ["/", "/manifest.json", "/logo.svg", "/favicon.svg"];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(key => key !== CACHE).map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);

  if (
    request.method !== "GET" ||
    url.origin !== self.location.origin ||
    url.pathname.endsWith("/lotes.json")
  ) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).then(response => {
        if (response.ok) {
          event.waitUntil(
            caches.open(CACHE).then(cache => cache.put(request, response.clone()))
          );
        }
        return response;
      }).catch(async () => {
        return (await caches.match(request)) || caches.match("/");
      })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) {
        event.waitUntil(
          caches.open(CACHE).then(cache => cache.put(request, response.clone()))
        );
      }
      return response;
    }))
  );
});
