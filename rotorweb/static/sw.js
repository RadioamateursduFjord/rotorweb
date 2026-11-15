// RotorWeb — service worker minimal.
// Le rotor se contrôle en direct : rien n'est mis en cache, sauf les icônes.
// Sans réseau, une page « hors ligne » s'affiche au lieu d'une erreur.
const CACHE = "rotorweb-v2.1";
const ASSETS = ["/icon-192.png", "/icon-512.png", "/icon-maskable-192.png", "/icon-maskable-512.png",
                "/favicon.png", "/favicon.svg", "/logo.svg", "/wordmark.svg", "/logo-horizontal.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname === "/ws") return;
  if (ASSETS.includes(url.pathname)) {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
    return;
  }
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).catch(() => new Response(
      `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
       <body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#0e1319;color:#e6edf3;font-family:system-ui;text-align:center">
       <div><h2>Rotor hors ligne</h2><p style="color:#8b9bb0">Le Raspberry Pi n'est pas joignable.<br>Vérifie le réseau (Wi-Fi ou VPN).</p>
       <button onclick="location.reload()" style="padding:12px 20px;border-radius:10px;border:0;background:#2f81f7;color:#fff;font-size:16px">Réessayer</button></div>`,
      { headers: { "Content-Type": "text/html; charset=utf-8" } })));
  }
});
