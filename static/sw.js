const CACHE = 'wilo-v6';
const SHELL = ['/', '/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // 저장 · 업로드(POST/PUT/DELETE)는 건드리지 않고 브라우저가 바로 보내게 한다.
  // 아이폰 사파리는 서비스워커를 거치면 첨부 파일(사진)이 빠지는 버그가 있다.
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (e.request.method === 'GET') {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
  } else if (e.request.mode === 'navigate') {
    // 페이지(HTML)는 네트워크 우선 - 업데이트가 바로 반영되도록
    e.respondWith(
      fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      }).catch(() => caches.match(e.request))
    );
  } else {
    // 화면 파일도 네트워크 우선 — 업데이트가 바로 반영되고, 오프라인일 때만 캐시 사용
    e.respondWith(
      fetch(e.request).then(res => {
        if (e.request.method === 'GET' && res.ok && url.origin === location.origin) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => caches.match(e.request).then(cached => cached || caches.match('/')))
    );
  }
});
