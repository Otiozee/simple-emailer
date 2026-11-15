"use strict";

const CACHE_NAME = "simple-emailer-0.1.0";
const STATIC_ASSETS = [
  "/",
  "/styles.css",
  "/app.js",
  "/manifest.webmanifest",
  "/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)),
    )).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const requestUrl = new URL(event.request.url);
  if (
    event.request.method !== "GET"
    || requestUrl.origin !== self.location.origin
    || requestUrl.pathname.startsWith("/api/")
    || requestUrl.search
    || !STATIC_ASSETS.includes(requestUrl.pathname)
  ) {
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (!response.ok) return response;
        const copy = response.clone();
        return caches.open(CACHE_NAME)
          .then((cache) => cache.put(event.request, copy))
          .then(() => response);
      })
      .catch(() => caches.match(event.request)),
  );
});
