/* SM Manager service worker — build {{ build_id }}
 *
 * Deliberately small. Pages always come from the network (they carry live
 * approvals and account data, so they are never stored on the phone); when
 * there is no connection the offline page is shown instead. Static files
 * (CSS, scripts, icons) are cached so the app starts fast and the offline
 * page can draw itself. Nothing else is intercepted: form posts, htmx
 * requests and other sites go straight to the network.
 */
'use strict';

const BUILD = '{{ build_id }}';
const STATIC_CACHE = 'smm-static-' + BUILD;
const OFFLINE_URL = '{{ offline_url }}';
const PRECACHE = {{ precache|safe }};

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith('smm-') && key !== STATIC_CACHE).map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match(OFFLINE_URL, { ignoreSearch: true }).then((page) =>
          page || new Response('<!doctype html><meta name="viewport" content="width=device-width"><title>Offline</title><p style="font:16px system-ui;padding:24px">You are offline. Reconnect and try again.</p>', {
            status: 503,
            headers: { 'Content-Type': 'text/html; charset=utf-8' },
          })
        )
      )
    );
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    // Stale-while-revalidate: answer from the cache when we can, refresh it in the background.
    event.respondWith(
      caches.open(STATIC_CACHE).then((cache) =>
        cache.match(request).then((cached) => {
          const network = fetch(request)
            .then((response) => {
              if (response && response.ok && response.type === 'basic') {
                cache.put(request, response.clone());
              }
              return response;
            })
            .catch(() => cached);
          return cached || network;
        })
      )
    );
  }
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});
