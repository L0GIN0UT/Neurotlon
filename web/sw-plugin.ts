import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Plugin } from 'vite'

// Файлы из public/, которых нет в бандле, но нужны оболочке приложения офлайн.
const STATIC_FILES = ['/favicon.svg', '/icon.svg', '/manifest.webmanifest']

/** Окно стенда (Electron) работает без service worker, планшету его файлы не нужны. */
const isStationFile = (name: string): boolean => /(^|\/)station[.-]/.test(name)

/**
 * Пишет sw.js после сборки: список файлов оболочки приложения известен только тогда.
 * Кэшируются только свои файлы, запросы к /api не трогаются, внешних адресов нет.
 */
export function serviceWorkerPlugin(): Plugin {
  let publicDir = ''
  return {
    name: 'neurotlon-service-worker',
    apply: 'build',
    configResolved(config) {
      publicDir = config.publicDir
    },
    generateBundle(_options, bundle) {
      const assets = Object.keys(bundle)
        .filter((name) => name !== 'index.html' && !isStationFile(name))
        .map((name) => `/${name}`)
      const files = ['/', ...assets, ...STATIC_FILES].sort()
      const source = buildServiceWorker(files, hashPublicFiles(publicDir))
      this.emitFile({
        type: 'asset',
        fileName: 'sw.js',
        source,
      })
    },
  }
}

/** Хеш содержимого файлов из public/: смена манифеста или иконки обновляет кэш. */
export function hashPublicFiles(publicDir: string, names: readonly string[] = STATIC_FILES): string {
  const hash = createHash('sha256')
  for (const name of names) {
    const file = join(publicDir, name)
    hash.update(name)
    if (publicDir && existsSync(file)) hash.update(readFileSync(file))
  }
  return hash.digest('hex')
}

export function buildServiceWorker(files: readonly string[], publicHash: string): string {
  // Версия кэша зависит от имён файлов сборки (в них есть хеши содержимого) и файлов public/.
  const version = createHash('sha256')
    .update(files.join('|'))
    .update(publicHash)
    .digest('hex')
    .slice(0, 12)
  return `const CACHE = 'neurotlon-shell-${version}'
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
          // в кэш попадает только успешный ответ нашего же сервера
          if (response.ok && response.type === 'basic') {
            const copy = response.clone()
            void caches.open(CACHE).then((cache) => cache.put('/', copy))
          }
          return response
        })
        .catch(() => caches.match('/')),
    )
    return
  }

  event.respondWith(caches.match(request).then((cached) => cached ?? fetch(request)))
})
`
}
