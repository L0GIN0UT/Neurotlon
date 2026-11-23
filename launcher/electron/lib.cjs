'use strict'
// Чистые функции оболочки: без Electron, проверяются `node --test`.

const path = require('node:path')

const EXIT_RESTART = 75 // лаунчер сохранил настройки и просит запустить его заново
const RESTART_DELAY_MS = 2000
const CRASH_WINDOW_MS = 60_000
const MAX_CRASHES = 5

/** Разбор аргументов: `--config путь`, `--windowed`, `--dev`. */
function parseArgs(argv) {
  const result = { config: null, windowed: false, dev: false, setup: false }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--windowed') result.windowed = true
    else if (arg === '--dev') result.dev = true
    else if (arg === '--setup') result.setup = true
    else if (arg === '--config') {
      result.config = argv[i + 1] ?? null
      i += 1
    }
  }
  return result
}

/** Команда лаунчера из окружения: «uv run neurotlon-launcher» → файл и аргументы. */
function splitCommand(text) {
  const parts = String(text ?? '').trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return { file: 'neurotlon-launcher', args: [] }
  return { file: parts[0], args: parts.slice(1) }
}

/** Порт из строки `{"ready": true, "port": N}`, которую лаунчер печатает при запуске. */
function parseReadyLine(line) {
  try {
    const data = JSON.parse(line)
    const port = data?.port
    return data?.ready === true && Number.isInteger(port) && port > 0 && port < 65536 ? port : null
  } catch {
    return null
  }
}

/** Файл внутри `root` для адреса `app://…`; `null`, если путь выходит наружу. */
function resolveInside(root, urlPath) {
  const relative = decodeURIComponent(urlPath).replace(/^\/+/, '') || 'station.html'
  const full = path.resolve(root, relative)
  const base = path.resolve(root) + path.sep
  return full.startsWith(base) ? full : null
}

/** Политика содержимого: только свои файлы и мост на 127.0.0.1:<порт>. */
function contentSecurityPolicy(port) {
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    `connect-src http://127.0.0.1:${port}`,
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
  ].join('; ')
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
}

const mimeFor = (file) => MIME[path.extname(file).toLowerCase()] ?? 'application/octet-stream'

/**
 * Что делать, когда лаунчер вышел сам. `crashes` — время прежних аварий (мс), массив дополняется.
 * Выход по просьбе (код 75) — сразу заново; авария — через 2 с; больше 5 аварий за минуту — стоп.
 */
function nextAction(code, crashes, now) {
  if (code === EXIT_RESTART) return { action: 'restart', delayMs: 0 }
  crashes.push(now)
  while (crashes.length > 0 && now - crashes[0] > CRASH_WINDOW_MS) crashes.shift()
  if (crashes.length > MAX_CRASHES) return { action: 'quit', code: code || 1 }
  return { action: 'restart', delayMs: RESTART_DELAY_MS }
}

/**
 * Источник страницы: схема и хост. `new URL('app://x').origin` для своей схемы даёт «null»,
 * поэтому по нему разрешение на камеру не сравнить.
 */
function originOf(value) {
  try {
    const url = new URL(value)
    return url.host ? `${url.protocol}//${url.host}` : ''
  } catch {
    return ''
  }
}

/**
 * Источник страницы: схема и хост. `new URL('app://x').origin` для своей схемы даёт «null»,
 * поэтому по нему разрешение на камеру не сравнить.
 */
function originOf(value) {
  try {
    const url = new URL(value)
    return url.host ? `${url.protocol}//${url.host}` : ''
  } catch {
    return ''
  }
}

/** Первая `.exe` в папке (игра, вложенная в установщик); `''`, если папки или файла нет. */
function firstExe(dir) {
  try {
    const name = fs
      .readdirSync(dir)
      .sort()
      .find((entry) => entry.toLowerCase().endsWith('.exe') && fs.statSync(path.join(dir, entry)).isFile())
    return name ? path.join(dir, name) : ''
  } catch {
    return ''
  }
}

module.exports = { originOf, EXIT_RESTART, nextAction, parseArgs, splitCommand, parseReadyLine, resolveInside, contentSecurityPolicy, mimeFor }
