'use strict'
// Чистые функции оболочки: без Electron, проверяются `node --test`.

const fs = require('node:fs')
const path = require('node:path')

const EXIT_RESTART = 75 // лаунчер сохранил настройки и просит запустить его заново
const RESTART_DELAY_MS = 2000
const CRASH_WINDOW_MS = 60_000
const MAX_CRASHES = 5
const READY_TIMEOUT_MS = 60_000 // холодный запуск PyInstaller с антивирусом бывает долгим
const STOP_TIMEOUT_MS = 3000
const AUTO_RETRIES = 2 // сколько раз повторить запуск ядра само, прежде чем показать ошибку
const LOG_MAX_BYTES = 1024 * 1024

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

/** Повторять ли запуск ядра сам: `attempt` — номер только что неудавшейся попытки (с 1). */
function shouldAutoRetry(attempt) {
  return attempt <= AUTO_RETRIES
}

/** Текст под заставкой во время запуска. */
function startingDetail(attempt, seconds) {
  const retry = attempt > 1 ? ` (попытка ${attempt})` : ''
  return `Подождите, идёт запуск${retry}… ${seconds} с`
}

/** JS для страницы-заставки: переключает состояние и подставляет тексты (через textContent). */
function splashScript(state) {
  const kind = state.kind === 'error' ? 'error' : 'starting'
  return (
    `document.body.dataset.state = ${JSON.stringify(kind)};` +
    `document.getElementById('title').textContent = ${JSON.stringify(String(state.title ?? ''))};` +
    `document.getElementById('detail').textContent = ${JSON.stringify(String(state.detail ?? ''))};`
  )
}

const WIN = path.win32
const trimSep = (value) => {
  let end = value.length
  while (end > 0 && value[end - 1] === WIN.sep) end -= 1
  return value.slice(0, end)
}
const winKey = (value) => WIN.normalize(String(value)).toLowerCase()

/** Лежит ли файл внутри одной из папок `roots` (без учёта регистра, как в Windows). */
function isInside(file, roots) {
  const key = winKey(file)
  return roots.some((root) => key.startsWith(trimSep(winKey(root)) + WIN.sep))
}

/**
 * Процессы из вывода `ConvertTo-Json` (один объект или массив) → [{pid, path, created}].
 * `created` — время создания строкой (FileTime): по нему перед убийством убеждаемся, что
 * под этим pid всё ещё тот же процесс, а не новый с переиспользованным номером.
 */
function parseProcessList(text) {
  try {
    const data = JSON.parse(String(text).trim() || '[]')
    return (Array.isArray(data) ? data : [data])
      .map((item) => ({ pid: item?.ProcessId, path: item?.ExecutablePath, created: String(item?.Created ?? '') }))
      .filter((item) => Number.isInteger(item.pid) && typeof item.path === 'string' && item.path)
  } catch {
    return []
  }
}

/** Процессы нашей установки: путь к .exe внутри `roots`, кроме `exclude` (свой pid). */
function selectOrphans(processes, roots, exclude = []) {
  return processes.filter((p) => !exclude.includes(p.pid) && isInside(p.path, roots))
}

/** PowerShell: процессы с путём к .exe из СВОЕГО сеанса Windows (чужих пользователей не трогаем). */
const LIST_PROCESSES_SCRIPT =
  '[Console]::OutputEncoding = [Text.Encoding]::UTF8; ' +
  '$s = (Get-Process -Id $PID).SessionId; ' +
  'Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.SessionId -eq $s } | ' +
  'Select-Object ProcessId, ExecutablePath, @{ n = "Created"; e = { [string]$_.CreationDate.ToFileTimeUtc() } } | ' +
  'ConvertTo-Json -Compress'

/** PowerShell: завершает процесс (без потомков), только если pid и время создания совпали; оба из окружения. */
const KILL_VERIFIED_SCRIPT =
  '$p = Get-CimInstance Win32_Process -Filter ("ProcessId = " + [int]$env:NT_PID); ' +
  'if ($p -and [string]$p.CreationDate.ToFileTimeUtc() -eq $env:NT_CREATED) { ' +
  'Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }'

/**
 * Убивает осиротевшие процессы своей установки. `listProcesses` и `killVerified(pid, created)`
 * подставляются снаружи (в Windows — PowerShell), поэтому логика проверяется без системы.
 * Потомков не трогаем (`/T` тут нельзя: список мог устареть, а pid — достаться чужому процессу).
 */
async function killOrphans({ listProcesses, killVerified, roots, exclude = [], log = () => {} }) {
  let orphans
  try {
    orphans = selectOrphans(await listProcesses(), roots, exclude)
  } catch (error) {
    log(`не удалось получить список процессов: ${error.message}`)
    return []
  }
  for (const { pid, created } of orphans) {
    log(`снос сироты ${pid}`)
    try {
      await killVerified(pid, created)
    } catch (error) {
      log(`не удалось завершить ${pid}: ${error.message}`)
    }
  }
  return orphans.map((p) => p.pid)
}

/** Абсолютный путь к системной программе: PATH не используем (в нём может оказаться подмена). */
function systemExe(systemRoot, ...parts) {
  return WIN.join(systemRoot || 'C:\\Windows', 'System32', ...parts)
}

/** Хвост журнала не больше `maxBytes`: старое обрезается по границе строки. */
function trimLog(text, maxBytes) {
  const buffer = Buffer.from(text, 'utf8')
  if (buffer.length <= maxBytes) return text
  const tail = buffer.subarray(buffer.length - Math.floor(maxBytes / 2)).toString('utf8')
  const newline = tail.indexOf('\n')
  return newline >= 0 ? tail.slice(newline + 1) : tail
}

/** Журнал в файл: дописывает строки с временем, при превышении размера оставляет хвост. */
function createLog(file, { maxBytes = LOG_MAX_BYTES, now = () => new Date() } = {}) {
  let size = 0
  try {
    size = fs.statSync(file).size
  } catch {
    size = 0
  }
  const shrink = () => {
    try {
      fs.writeFileSync(file, trimLog(fs.readFileSync(file, 'utf8'), maxBytes))
      size = fs.statSync(file).size
    } catch {
      size = 0
    }
  }
  if (size > maxBytes) shrink()
  return (message) => {
    const line = `${now().toISOString()} ${message}\n`
    try {
      fs.appendFileSync(file, line)
      size += Buffer.byteLength(line)
      if (size > maxBytes) shrink()
    } catch {
      // журнал не должен ронять приложение
    }
  }
}

/**
 * Горячие клавиши окна: Ctrl+Q — выход, Ctrl+Alt+S — перезапуск с настройкой.
 * Клавиша берётся по физическому коду, не зависящему от раскладки; `key` — запасной вариант.
 */
function shortcutAction(input) {
  if (input.type !== 'keyDown' || !input.control) return null
  const code = input.code || ''
  const key = (input.key || '').toLowerCase()
  if (code === 'KeyQ' || (!code && (key === 'q' || key === 'й'))) return 'quit'
  if (input.alt && (code === 'KeyS' || (!code && (key === 's' || key === 'ы')))) return 'setup'
  return null
}

module.exports = {
  AUTO_RETRIES,
  EXIT_RESTART,
  LOG_MAX_BYTES,
  READY_TIMEOUT_MS,
  STOP_TIMEOUT_MS,
  contentSecurityPolicy,
  createLog,
  isInside,
  KILL_VERIFIED_SCRIPT,
  LIST_PROCESSES_SCRIPT,
  killOrphans,
  mimeFor,
  nextAction,
  originOf,
  parseArgs,
  parseProcessList,
  parseReadyLine,
  resolveInside,
  selectOrphans,
  shortcutAction,
  shouldAutoRetry,
  splashScript,
  splitCommand,
  startingDetail,
  systemExe,
  trimLog,
}
