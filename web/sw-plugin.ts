import { createHash } from 'node:crypto'
import type { Plugin } from 'vite'

// Файлы из public/, которых нет в бандле, но нужны оболочке приложения офлайн.
const STATIC_FILES = ['/favicon.svg', '/icon.svg', '/manifest.webmanifest']

/**
 * Пишет sw.js после сборки: список файлов оболочки приложения известен только тогда.
 * Кэшируются только свои файлы, запросы к /api не трогаются, внешних адресов нет.
 */
export function serviceWorkerPlugin(): Plugin {
  return {
    name: 'neurotlon-service-worker',
    apply: 'build',
    generateBundle(_options, bundle) {
      const assets = Object.keys(bundle)
        .filter((name) => name !== 'index.html')
        .map((name) => `/${name}`)
      const files = ['/', ...assets, ...STATIC_FILES].sort()
      // Версия кэша зависит от имён файлов (в них есть хеши содержимого).
      const version = createHash('sha256').update(files.join('|')).digest('hex').slice(0, 12)
      this.emitFile({
        type: 'asset',
        fileName: 'sw.js',
        source: `const CACHE = 'neurotlon-shell-${version}'
const FILES = ${JSON.stringify(files)}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(FILES))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    // Любая страница приложения отдаёт оболочку; при наличии связи берём свежую.
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          void caches.open(CACHE).then((cache) => cache.put('/', copy))
          return response
        })
        .catch(() => caches.match('/')),
    )
    return
  }

  event.respondWith(caches.match(request).then((cached) => cached ?? fetch(request)))
})
`,
      })
    },
  }
}
