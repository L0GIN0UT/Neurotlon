'use strict'
// Окно стенда: запускает Python-лаунчер, открывает интерфейс из web/dist на весь экран.
// Лаунчер сам понимает, когда нужна первая настройка. Ctrl+Alt+S открывает настройку повторно.

const { spawn } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const readline = require('node:readline')
const { pathToFileURL } = require('node:url')
const { app, BrowserWindow, dialog, ipcMain, net, protocol, session } = require('electron')
const lib = require('./lib.cjs')

const READY_TIMEOUT_MS = 30_000
const STOP_TIMEOUT_MS = 5_000
const SCHEME = 'app'

protocol.registerSchemesAsPrivileged([
  { scheme: SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
])

const options = lib.parseArgs(process.argv.slice(1))
// В собранном приложении интерфейс лежит рядом (resources/web), при разработке — в web/dist.
const bundledWeb = app.isPackaged
  ? path.join(process.resourcesPath, 'web')
  : path.join(__dirname, '..', '..', 'web', 'dist')
const webDir = path.resolve(process.env.NEUROTLON_WEB_DIR ?? bundledWeb)
const ICON = path.join(__dirname, 'build', 'icon.png')
const devUrl = process.env.NEUROTLON_DEV_URL ?? ''

let configPath = ''
let child = null
let mainWindow = null
let bundleServed = false
let quitting = false
let restarting = false
const crashes = []

function fail(message) {
  console.error(`Ошибка запуска: ${message}`)
  app.exit(2)
}

/** Запускает лаунчер и ждёт строку готовности с портом моста. */
function startLauncher(token, { setup }) {
  const { file, args } = lib.splitCommand(process.env.NEUROTLON_LAUNCHER_CMD)
  const full = [...args, '--config', configPath, '--ui-token', token]
  if (setup) full.push('--setup')
  const proc = spawn(file, full, { stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true })
  child = proc
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('лаунчер не ответил за 30 с')), READY_TIMEOUT_MS)
    proc.once('error', (error) => {
      clearTimeout(timer)
      reject(new Error(`не удалось запустить «${file}»: ${error.message}`))
    })
    proc.once('exit', (code) => {
      clearTimeout(timer)
      if (child === proc) child = null
      if (!quitting && !restarting) onLauncherExit(code)
      reject(new Error(`лаунчер завершился с кодом ${code}`))
    })
    readline.createInterface({ input: proc.stdout }).on('line', (line) => {
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

/** Лаунчер вышел сам: после сохранения настройки (код 75) стартуем заново, при аварии — с паузой. */
function onLauncherExit(code) {
  const next = lib.nextAction(code, crashes, Date.now())
  if (next.action === 'quit') {
    console.error(`Лаунчер завершается снова и снова (код ${code}), останавливаюсь.`)
    app.exit(next.code)
    return
  }
  setTimeout(() => void launch({ setup: false }), next.delayMs)
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

/** Отдаёт web/dist по `app://`. Порт моста попадает в CSP, поэтому обработчик ставится на каждый запуск. */
function serveBundle(port) {
  if (bundleServed) protocol.unhandle(SCHEME)
  bundleServed = true
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
  const allowed = (permission, origin) => {
    const ok = permission === 'media' && origins.includes(lib.originOf(origin))
    if (!ok && options.dev) console.log(`[разрешения] отказ: ${permission} для ${origin}`)
    return ok
  }
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) =>
    callback(allowed(permission, details.requestingUrl)),
  )
  // Проверка может прийти с пустым адресом (так делает перечисление камер): берём адрес окна.
  session.defaultSession.setPermissionCheckHandler((contents, permission, origin, details) =>
    allowed(permission, origin || details?.requestingUrl || contents?.getURL() || ''),
  )
}

function createWindow(port, token) {
  const window = new BrowserWindow({
    backgroundColor: '#0b0f1a',
    icon: ICON,
    title: 'Нейротлон',
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
  if (options.dev) {
    // Консоль страницы — в stdout: ошибки CSP и сети видно без открытия инструментов
    window.webContents.on('console-message', (event, ...rest) =>
      console.log('[страница]', event.message ?? rest[1]),
    )
  }
  window.webContents.on('will-navigate', (event) => event.preventDefault())
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown' || !input.control) return
    const key = input.key.toLowerCase()
    if (key === 'q') {
      event.preventDefault()
      app.quit()
    } else if (key === 's' && input.alt) {
      event.preventDefault()
      void reconfigure()
    }
  })
  void window.loadURL(devUrl || `${SCHEME}://station/station.html`)
  return window
}

/** Запускает лаунчер и открывает для него окно; прежнее окно (с прежним токеном) закрывается. */
async function launch({ setup }) {
  const token = crypto.randomBytes(24).toString('hex')
  let port
  try {
    port = await startLauncher(token, { setup })
  } catch (error) {
    if (!quitting && !restarting) console.error(error.message)
    return
  }
  if (!devUrl) serveBundle(port)
  const previous = mainWindow
  mainWindow = createWindow(port, token)
  if (previous && !previous.isDestroyed()) previous.destroy()
}

/** Ctrl+Alt+S: остановить лаунчер и запустить его с экраном настройки. */
async function reconfigure() {
  restarting = true
  try {
    await stopLauncher()
    await launch({ setup: true })
  } finally {
    restarting = false
  }
}

ipcMain.handle('pick-file', async (event, kind) => {
  const filters =
    kind === 'game'
      ? [{ name: 'Игра (.exe)', extensions: ['exe'] }]
      : kind === 'cert'
        ? [{ name: 'Сертификат', extensions: ['crt', 'pem', 'cer'] }]
        : null
  if (!filters || !mainWindow || event.sender !== mainWindow.webContents) return null
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openFile'], filters })
  return result.canceled ? null : (result.filePaths[0] ?? null)
})

async function main() {
  configPath = options.config ?? path.join(app.getPath('userData'), 'launcher.toml')
  fs.mkdirSync(path.dirname(configPath), { recursive: true })
  if (!devUrl && !fs.existsSync(path.join(webDir, 'station.html'))) {
    return fail(`нет собранного интерфейса: ${webDir} (соберите web: npm run build)`)
  }
  lockPermissions([`${SCHEME}://station`, ...(devUrl ? [lib.originOf(devUrl)] : [])])
  await launch({ setup: options.setup })
}

// Своё имя для Windows: группа значков на панели задач и уведомления без «Electron».
app.setAppUserModelId('ru.neurotlon.station')

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.whenReady().then(main)
  app.on('window-all-closed', () => {
    if (!restarting) app.quit()
  })
  app.on('before-quit', (event) => {
    if (quitting) return
    quitting = true
    event.preventDefault()
    void stopLauncher().then(() => app.quit())
  })
}
