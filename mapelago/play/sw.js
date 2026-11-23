// Pages come fresh from the network when there is one, and from the saved copy when there isn't.
// Everything else (map data, fonts, icons) is answered from the saved copy at once and refreshed behind the scenes.
const C = "mapelago-0.8.1";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== C).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const r = e.request;
  if (r.method !== "GET" || new URL(r.url).origin !== location.origin) return;
  if (r.mode === "navigate") {
    e.respondWith(fetch(r).then((res) => { if (res.ok) { const copy = res.clone(); caches.open(C).then((c) => c.put(r, copy)); } return res; }).catch(() => caches.match(r, { ignoreSearch: true }).then((hit) => hit || caches.match("./"))));
    return;
  }
  e.respondWith(caches.open(C).then((c) => c.match(r).then((hit) => { const net = fetch(r).then((res) => { if (res.ok) c.put(r, res.clone()); return res; }).catch(() => hit); return hit || net; })));
});
