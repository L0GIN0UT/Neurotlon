'use strict'
// Окно стенда: запускает Python-лаунчер, открывает интерфейс из web/dist на весь экран.
// Лаунчер сам понимает, когда нужна первая настройка. Ctrl+Alt+S открывает настройку повторно.
// Пока ядро запускается, виден splash.html; при сбое на нём «Повторить» и «Закрыть».

const { execFile, spawn } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const readline = require('node:readline')
const { pathToFileURL } = require('node:url')
const { app, BrowserWindow, dialog, ipcMain, net, protocol, session } = require('electron')
const lib = require('./lib.cjs')

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
// В установщике рядом лежат ядро лаунчера (core), мост датчиков (bridge) и все игры (games).
const bundledGames = app.isPackaged ? path.join(process.resourcesPath, 'games') : ''
const bundledBridge = app.isPackaged
  ? path.join(process.resourcesPath, 'bridge', 'neurotlon-bridge.exe')
  : ''
const devUrl = process.env.NEUROTLON_DEV_URL ?? ''

let configPath = ''
let child = null
let mainWindow = null
let splashWindow = null
let launchId = 0
let bundleServed = false
let quitting = false
let restarting = false
let log = () => {}
const crashes = []

function fail(message) {
  log(`ошибка запуска: ${message}`)
  console.error(`Ошибка запуска: ${message}`)
  app.exit(2)
}

/** Ядро лаунчера: в установленном приложении `.exe` рядом, при разработке команда из окружения. */
function launcherCommand() {
  if (app.isPackaged && !process.env.NEUROTLON_LAUNCHER_CMD) {
    return { file: path.join(process.resourcesPath, 'core', 'neurotlon-launcher.exe'), args: [] }
  }
  return lib.splitCommand(process.env.NEUROTLON_LAUNCHER_CMD)
}

/** Завершает процесс вместе с потомками: в Windows `proc.kill()` убил бы только само ядро. */
function killTree(pid) {
  return new Promise((resolve) => {
    if (process.platform === 'win32') {
      execFile('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, timeout: 10_000 }, () =>
        resolve(),
      )
      return
    }
    try {
      process.kill(pid, 'SIGKILL')
    } catch {
      // уже завершён
    }
    resolve()
  })
}

/** Процессы с известным путём к .exe (Windows: Get-CimInstance); на других системах пусто. */
function listProcesses() {
  if (process.platform !== 'win32') return Promise.resolve([])
  const script =
    '[Console]::OutputEncoding = [Text.Encoding]::UTF8; ' +
    'Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath } | ' +
    'Select-Object ProcessId, ExecutablePath | ConvertTo-Json -Compress'
  return new Promise((resolve, reject) => {
    execFile(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-Command', script],
      { windowsHide: true, timeout: 20_000, maxBuffer: 32 * 1024 * 1024, encoding: 'utf8' },
      (error, stdout) => (error ? reject(error) : resolve(lib.parseProcessList(stdout))),
    )
  })
}

/** Сироты прошлого запуска: ядро, мост и игры именно из папок этой установки. */
function killStaleProcesses() {
  if (!app.isPackaged) return Promise.resolve([])
  const roots = ['core', 'bridge', 'games'].map((name) => path.join(process.resourcesPath, name))
  return lib.killOrphans({ listProcesses, killTree, roots, exclude: [process.pid], log })
}

/** Запускает лаунчер и ждёт строку готовности с портом моста. */
function startLauncher(token, { setup }) {
  const { file, args } = launcherCommand()
  const full = [...args, '--config', configPath, '--ui-token', token]
  if (bundledGames && fs.existsSync(bundledGames)) full.push('--games-dir', bundledGames)
  if (bundledBridge && fs.existsSync(bundledBridge)) full.push('--bridge-exe', bundledBridge)
  if (setup) full.push('--setup')
  log(`запуск ядра: ${file} ${full.join(' ').replace(token, '***')}`)
  const proc = spawn(file, full, { stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true })
  child = proc
  let ready = false
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`ядро не ответило за ${lib.READY_TIMEOUT_MS / 1000} с`)),
      lib.READY_TIMEOUT_MS,
    )
    proc.once('error', (error) => {
      clearTimeout(timer)
      reject(new Error(`не удалось запустить «${file}»: ${error.message}`))
    })
    proc.once('exit', (code) => {
      clearTimeout(timer)
      if (child === proc) child = null
      log(`ядро завершилось с кодом ${code}`)
      // До готовности сбой разбирает launch() (повтор или ошибка в окне), после — onLauncherExit.
      if (ready && !quitting && !restarting) onLauncherExit(code)
      reject(new Error(`ядро завершилось с кодом ${code}`))
    })
    readline.createInterface({ input: proc.stdout }).on('line', (line) => {
      const port = lib.parseReadyLine(line)
      if (port !== null) {
        clearTimeout(timer)
        ready = true
        log(`ядро готово, порт ${port}`)
        resolve(port)
      } else {
        log(`ядро: ${line}`)
        console.log(line)
      }
    })
  })
}

/** Лаунчер вышел сам: после сохранения настройки (код 75) стартуем заново, при аварии — с паузой. */
function onLauncherExit(code) {
  const next = lib.nextAction(code, crashes, Date.now())
  if (next.action === 'quit') {
    log(`ядро завершается снова и снова (код ${code}), останавливаюсь`)
    console.error(`Лаунчер завершается снова и снова (код ${code}), останавливаюсь.`)
    app.exit(next.code)
    return
  }
  setTimeout(() => void launch({ setup: false }), next.delayMs)
}

/** Останавливает лаунчер: закрытый stdin — сигнал завершиться штатно, через 3 с сносим дерево. */
function stopLauncher() {
  const proc = child
  if (!proc || proc.exitCode !== null) return Promise.resolve()
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      log(`ядро не закрылось за ${lib.STOP_TIMEOUT_MS / 1000} с, снос дерева процессов`)
      void killTree(proc.pid).then(resolve)
    }, lib.STOP_TIMEOUT_MS)
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

/** Общие настройки окна: во весь экран, в киоске — кроме режимов `--windowed` и `--dev`. */
function baseWindowOptions() {
  return {
    backgroundColor: '#0b0f1a',
    icon: ICON,
    title: 'Нейротлон',
    fullscreen: !options.windowed,
    kiosk: !options.windowed && !options.dev,
    width: 1280,
    height: 720,
    autoHideMenuBar: true,
    show: false,
  }
}

/** Ctrl+Q — выход; Ctrl+Alt+S (если задан обработчик) — перезапуск с настройкой. */
function handleShortcuts(window, onSetup) {
  window.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown' || !input.control) return
    const key = input.key.toLowerCase()
    if (key === 'q') {
      event.preventDefault()
      log('выход: Ctrl+Q')
      app.quit()
    } else if (key === 's' && input.alt && onSetup) {
      event.preventDefault()
      onSetup()
    }
  })
}

/** Заставка: локальная страница сразу, пока ядро запускается; при сбое — «Повторить» и «Закрыть». */
function showSplash(state) {
  if (!splashWindow || splashWindow.isDestroyed()) {
    const window = new BrowserWindow({
      ...baseWindowOptions(),
      webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, devTools: false },
    })
    splashWindow = window
    window.once('ready-to-show', () => window.show())
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    window.webContents.on('will-navigate', (event, url) => {
      event.preventDefault()
      if (url === `${SCHEME}://action/retry`) void launch({ setup: false })
      else if (url === `${SCHEME}://action/close`) app.quit()
    })
    handleShortcuts(window, null)
    window.on('closed', () => {
      if (splashWindow === window) splashWindow = null
    })
    void window.loadFile(path.join(__dirname, 'splash.html'))
  }
  const contents = splashWindow.webContents
  const apply = () => void contents.executeJavaScript(lib.splashScript(state)).catch(() => {})
  if (contents.isLoading()) contents.once('did-finish-load', apply)
  else apply()
}

function createWindow(port, token) {
  const window = new BrowserWindow({
    ...baseWindowOptions(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      additionalArguments: [`--bridge-port=${port}`, `--bridge-token=${token}`],
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      devTools: options.dev,
    },
  })
  window.once('ready-to-show', () => {
    window.show()
    // Заставка и прежнее окно (с прежним токеном) больше не нужны.
    for (const old of [splashWindow, mainWindow]) {
      if (old && old !== window && !old.isDestroyed()) old.destroy()
    }
    mainWindow = window
  })
  if (options.dev) {
    // Консоль страницы — в stdout: ошибки CSP и сети видно без открытия инструментов
    window.webContents.on('console-message', (event, ...rest) =>
      console.log('[страница]', event.message ?? rest[1]),
    )
  }
  window.webContents.on('will-navigate', (event) => event.preventDefault())
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  handleShortcuts(window, () => void reconfigure())
  void window.loadURL(devUrl || `${SCHEME}://station/station.html`)
  return window
}

/**
 * Запускает лаунчер и открывает для него окно. Заставка видна сразу; при сбое ядро стартует
 * ещё раз-другой само, потом заставка показывает ошибку с кнопками. Невидимым приложение не бывает.
 */
async function launch({ setup }) {
  const id = (launchId += 1)
  const token = crypto.randomBytes(24).toString('hex')
  let port = null
  for (let attempt = 1; port === null; attempt += 1) {
    const started = Date.now()
    const tick = () => {
      const seconds = Math.round((Date.now() - started) / 1000)
      showSplash({ kind: 'starting', title: 'Запуск стенда…', detail: lib.startingDetail(attempt, seconds) })
    }
    tick()
    const timer = setInterval(tick, 1000)
    let lastError = ''
    try {
      await killStaleProcesses()
      if (id !== launchId || quitting) return
      port = await startLauncher(token, { setup })
    } catch (error) {
      lastError = error.message
      log(`попытка ${attempt} не удалась: ${lastError}`)
      const proc = child
      if (proc && proc.exitCode === null) await killTree(proc.pid)
      if (child === proc) child = null
    } finally {
      clearInterval(timer)
    }
    if (id !== launchId || quitting) return
    if (port === null && !lib.shouldAutoRetry(attempt)) {
      const logFile = path.join(app.getPath('userData'), 'electron.log')
      showSplash({
        kind: 'error',
        title: 'Не удалось запустить стенд',
        detail: `${lastError}. Подробности в журнале: ${logFile}`,
      })
      return
    }
  }
  if (!devUrl) serveBundle(port)
  createWindow(port, token)
}

/** Ctrl+Alt+S: остановить лаунчер и запустить его с экраном настройки. */
async function reconfigure() {
  restarting = true
  log('перезапуск с настройкой (Ctrl+Alt+S)')
  try {
    await stopLauncher()
  } finally {
    restarting = false
  }
  await launch({ setup: true })
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
  log = lib.createLog(path.join(app.getPath('userData'), 'electron.log'))
  log(`старт ${app.getVersion()}, упаковано: ${app.isPackaged}, ядро: ${launcherCommand().file}`)
  process.on('uncaughtException', (error) => log(`необработанная ошибка: ${error.stack ?? error}`))
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
  // Повторный запуск ярлыка выводит на передний план уже открытое окно.
  app.on('second-instance', () => {
    const window = [mainWindow, splashWindow].find((item) => item && !item.isDestroyed())
    if (!window) return
    if (window.isMinimized()) window.restore()
    window.focus()
  })
  app.on('window-all-closed', () => {
    if (!restarting) app.quit()
  })
  app.on('before-quit', (event) => {
    if (quitting) return
    quitting = true
    event.preventDefault()
    const started = Date.now()
    log('закрытие: остановка ядра')
    void stopLauncher().then(() => {
      log(`закрытие: готово за ${Date.now() - started} мс`)
      app.exit(0)
    })
  })
}
