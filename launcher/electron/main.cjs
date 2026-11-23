'use strict'
// Окно стенда: запускает Python-лаунчер (`--ui web`), открывает интерфейс из web/dist на весь экран.

const { spawn } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const readline = require('node:readline')
const { pathToFileURL } = require('node:url')
const { app, BrowserWindow, net, protocol, session } = require('electron')
const lib = require('./lib.cjs')

const READY_TIMEOUT_MS = 30_000
const STOP_TIMEOUT_MS = 5_000
const SCHEME = 'app'

protocol.registerSchemesAsPrivileged([
  { scheme: SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
])

const options = lib.parseArgs(process.argv.slice(1))
const webDir = path.resolve(process.env.NEUROTLON_WEB_DIR ?? path.join(__dirname, '..', '..', 'web', 'dist'))
const devUrl = process.env.NEUROTLON_DEV_URL ?? ''
let child = null
let quitting = false

function fail(message) {
  console.error(`Ошибка запуска: ${message}`)
  app.exit(2)
}

/** Запускает лаунчер и ждёт строку готовности с портом моста. */
function startLauncher(token) {
  const { file, args } = lib.splitCommand(process.env.NEUROTLON_LAUNCHER_CMD)
  child = spawn(file, [...args, '--config', options.config, '--ui', 'web', '--ui-token', token], {
    stdio: ['pipe', 'pipe', 'inherit'],
    windowsHide: true,
  })
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('лаунчер не ответил за 30 с')), READY_TIMEOUT_MS)
    child.once('error', (error) => {
      clearTimeout(timer)
      reject(new Error(`не удалось запустить «${file}»: ${error.message}`))
    })
    child.once('exit', (code) => {
      clearTimeout(timer)
      if (!quitting) {
        console.error(`Лаунчер завершился (код ${code}).`)
        app.exit(code || 1) // перезапуск — задача оболочки запуска Windows
      }
      reject(new Error(`лаунчер завершился с кодом ${code}`))
    })
    readline.createInterface({ input: child.stdout }).on('line', (line) => {
      const port = lib.parseReadyLine(line)
      if (port !== null) {
        clearTimeout(timer)
        resolve(port)
      } else {
        console.log(line)
      }
    })
  })
}

/** Останавливает лаунчер: закрытый stdin — сигнал завершиться штатно, иначе через 5 с убиваем. */
function stopLauncher() {
  const proc = child
  if (!proc || proc.exitCode !== null) return Promise.resolve()
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      proc.kill()
      resolve()
    }, STOP_TIMEOUT_MS)
    proc.once('exit', () => {
      clearTimeout(timer)
      resolve()
    })
    proc.stdin.end()
  })
}

function serveBundle(port) {
  protocol.handle(SCHEME, async (request) => {
    const file = lib.resolveInside(webDir, new URL(request.url).pathname)
    if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      return new Response('Not found', { status: 404 })
    }
    const upstream = await net.fetch(pathToFileURL(file).toString())
    const headers = new Headers({
      'Content-Type': lib.mimeFor(file),
      'Content-Security-Policy': lib.contentSecurityPolicy(port),
      'Cache-Control': 'no-store',
    })
    return new Response(upstream.body, { status: upstream.status, headers })
  })
}

/** Камера нужна только своей странице; всё остальное (геолокация, микрофон…) запрещено. */
function lockPermissions(origins) {
  const allowed = (permission, origin) => permission === 'media' && origins.includes(origin)
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) =>
    callback(allowed(permission, new URL(details.requestingUrl).origin)),
  )
  session.defaultSession.setPermissionCheckHandler((contents, permission, origin) =>
    allowed(permission, origin),
  )
}

function createWindow(port, token) {
  const window = new BrowserWindow({
    backgroundColor: '#0b0f1a',
    fullscreen: !options.windowed,
    kiosk: !options.windowed && !options.dev,
    width: 1280,
    height: 720,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      additionalArguments: [`--bridge-port=${port}`, `--bridge-token=${token}`],
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      devTools: options.dev,
    },
  })
  window.once('ready-to-show', () => window.show())
  window.webContents.on('will-navigate', (event) => event.preventDefault())
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && input.control && input.key.toLowerCase() === 'q') {
      event.preventDefault()
      app.quit()
    }
  })
  void window.loadURL(devUrl || `${SCHEME}://station/station.html`)
  return window
}

async function main() {
  if (!options.config) return fail('укажите --config путь/к/launcher.toml')
  if (!devUrl && !fs.existsSync(path.join(webDir, 'station.html'))) {
    return fail(`нет собранного интерфейса: ${webDir} (соберите web: npm run build)`)
  }
  const token = crypto.randomBytes(24).toString('hex')
  let port
  try {
    port = await startLauncher(token)
  } catch (error) {
    return fail(error.message)
  }
  if (!devUrl) serveBundle(port)
  lockPermissions([`${SCHEME}://station`, ...(devUrl ? [new URL(devUrl).origin] : [])])
  createWindow(port, token)
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.whenReady().then(main)
  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', (event) => {
    if (quitting) return
    quitting = true
    event.preventDefault()
    void stopLauncher().then(() => app.quit())
  })
}
