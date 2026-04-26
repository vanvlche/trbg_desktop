"use strict";

const CACHE_VERSION = "quiet-relay-art-assets-2026-04-26";
const DEBUG_SW = false;

const CORE_ASSETS = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.json",
  "./offline.html",
  "./icons/icon-192.svg",
  "./icons/icon-512.svg",
  "./data/rules.json",
  "./data/affinities.json",
  "./data/characters.json",
  "./data/skills.json",
  "./data/enemies.json",
  "./data/bosses.json",
  "./data/weapons.json",
  "./data/relics.json",
  "./data/events.json",
  "./data/reward_tables.json",
  "./data/districts.json"
];

function debug(...args) {
  if (DEBUG_SW) {
    console.info("[Quiet Relay SW]", ...args);
  }
}

self.addEventListener("install", (event) => {
  debug("install", CACHE_VERSION);
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(CORE_ASSETS)),
  );
});

self.addEventListener("activate", (event) => {
  debug("activate", CACHE_VERSION);
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys
        .filter((key) => key !== CACHE_VERSION && key.startsWith("quiet-relay-"))
        .map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put("./index.html", copy));
          return response;
        })
        .catch(() => caches.match("./index.html").then((cached) => cached || caches.match("./offline.html"))),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_VERSION).then((cache) => {
              const path = `.${url.pathname.replace(self.registration.scope.replace(url.origin, ""), "/")}`;
              if (CORE_ASSETS.includes(path)) {
                cache.put(request, copy);
              }
            });
          }
          return response;
        })
        .catch(() => {
          if (request.destination === "document") {
            return caches.match("./offline.html");
          }
          return Response.error();
        });
    }),
  );
});
