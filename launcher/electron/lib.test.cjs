'use strict'
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')
const lib = require('./lib.cjs')

test('parseArgs reads the config path and flags', () => {
  assert.deepEqual(lib.parseArgs(['--config', 'a b/launcher.toml', '--windowed']), {
    config: 'a b/launcher.toml',
    windowed: true,
    dev: false,
    setup: false,
  })
  assert.deepEqual(lib.parseArgs([]), { config: null, windowed: false, dev: false, setup: false })
  assert.equal(lib.parseArgs(['--setup']).setup, true)
  assert.equal(lib.parseArgs(['--config']).config, null)
  assert.equal(lib.parseArgs(['--dev']).dev, true)
})

test('splitCommand splits on spaces and has a default', () => {
  assert.deepEqual(lib.splitCommand('uv run neurotlon-launcher'), {
    file: 'uv',
    args: ['run', 'neurotlon-launcher'],
  })
  assert.deepEqual(lib.splitCommand(''), { file: 'neurotlon-launcher', args: [] })
  assert.deepEqual(lib.splitCommand(undefined), { file: 'neurotlon-launcher', args: [] })
})

test('parseReadyLine accepts only a ready line with a valid port', () => {
  assert.equal(lib.parseReadyLine('{"ready": true, "port": 8799}'), 8799)
  for (const bad of ['', 'hello', '{"ready": false, "port": 1}', '{"ready": true}', '{"ready": true, "port": 0}', '{"ready": true, "port": 70000}', '{"ready": true, "port": "80"}']) {
    assert.equal(lib.parseReadyLine(bad), null, bad)
  }
})

test('resolveInside keeps requests inside the web directory', () => {
  const root = path.resolve('web-dist')
  assert.equal(lib.resolveInside(root, '/'), path.join(root, 'station.html'))
  assert.equal(lib.resolveInside(root, '/assets/a.js'), path.join(root, 'assets', 'a.js'))
  assert.equal(lib.resolveInside(root, '/../secret.txt'), null)
  assert.equal(lib.resolveInside(root, '/%2e%2e/secret.txt'), null)
  assert.equal(lib.resolveInside(root, '/assets/../../x'), null)
})

test('content security policy allows only the local bridge', () => {
  const csp = lib.contentSecurityPolicy(8799)
  assert.match(csp, /connect-src http:\/\/127\.0\.0\.1:8799(;|$)/)
  assert.match(csp, /default-src 'self'/)
  assert.doesNotMatch(csp, /https?:\/\/(?!127\.0\.0\.1)/)
  assert.doesNotMatch(csp, /unsafe-eval/)
})

test('mimeFor knows the bundle types', () => {
  assert.equal(lib.mimeFor('x.js'), 'text/javascript; charset=utf-8')
  assert.equal(lib.mimeFor('x.CSS'), 'text/css; charset=utf-8')
  assert.equal(lib.mimeFor('x.bin'), 'application/octet-stream')
})

test('nextAction restarts at once after a saved setup and does not count it as a crash', () => {
  const crashes = []
  assert.deepEqual(lib.nextAction(lib.EXIT_RESTART, crashes, 1000), { action: 'restart', delayMs: 0 })
  assert.deepEqual(crashes, [])
})

test('nextAction restarts after a crash with a delay and gives up on a crash loop', () => {
  const crashes = []
  for (let i = 0; i < 5; i += 1) {
    assert.deepEqual(lib.nextAction(1, crashes, 1000 + i), { action: 'restart', delayMs: 2000 })
  }
  assert.deepEqual(lib.nextAction(1, crashes, 1010), { action: 'quit', code: 1 })
})

test('nextAction forgets old crashes', () => {
  const crashes = []
  for (let i = 0; i < 5; i += 1) lib.nextAction(1, crashes, i)
  assert.equal(lib.nextAction(1, crashes, 200_000).action, 'restart')
  assert.equal(crashes.length, 1)
})

test('originOf works for the private app:// scheme and for http', () => {
  assert.equal(lib.originOf('app://station/station.html'), 'app://station')
  assert.equal(lib.originOf('app://station'), 'app://station')
  assert.equal(lib.originOf('http://127.0.0.1:5180/station.html?x=1'), 'http://127.0.0.1:5180')
  for (const bad of ['', 'nonsense', 'file:///C:/x.html']) assert.equal(lib.originOf(bad), '', bad)
})

const w = (...parts) => parts.join(path.win32.sep)

const ROOTS = [w('C:', 'Program Files', 'Нейротлон Стенд', 'resources', 'core'), w('C:', 'Program Files', 'Нейротлон Стенд', 'resources', 'bridge')]

test('selectOrphans picks only processes from our install folders', () => {
  const list = [
    { pid: 1, path: w('C:', 'Program Files', 'Нейротлон Стенд', 'resources', 'core', 'neurotlon-launcher.exe') },
    { pid: 2, path: w('c:', 'program files', 'нейротлон стенд', 'RESOURCES', 'bridge', 'neurotlon-bridge.exe') },
    { pid: 3, path: w('D:', 'other', 'resources', 'bridge', 'neurotlon-bridge.exe') },
    { pid: 4, path: w('C:', 'Program Files', 'Нейротлон Стенд', 'resources', 'core-evil', 'x.exe') },
    { pid: 5, path: w('C:', 'Program Files', 'Нейротлон Стенд', 'Нейротлон Стенд.exe') },
    { pid: 6, path: w('C:', 'Program Files', 'Нейротлон Стенд', 'resources', 'core', 'neurotlon-launcher.exe') },
  ]
  assert.deepEqual(lib.selectOrphans(list, ROOTS, [6]).map((p) => p.pid), [1, 2])
})

test('parseProcessList accepts one object, an array and garbage', () => {
  assert.deepEqual(lib.parseProcessList(JSON.stringify({ ProcessId: 7, ExecutablePath: w('C:', 'a.exe') })), [{ pid: 7, path: w('C:', 'a.exe'), created: '' }])
  assert.deepEqual(lib.parseProcessList('[{"ProcessId": 1, "ExecutablePath": "x"}, {"ProcessId": 2, "ExecutablePath": null}]'), [{ pid: 1, path: 'x', created: '' }])
  assert.deepEqual(lib.parseProcessList('not json'), [])
  assert.deepEqual(lib.parseProcessList(''), [])
})

test('killOrphans kills the selected tree and survives errors', async () => {
  const killed = []
  const logs = []
  const result = await lib.killOrphans({
    listProcesses: async () => [
      { pid: 1, path: w(ROOTS[0], 'a.exe') },
      { pid: 2, path: w(ROOTS[1], 'b.exe') },
      { pid: 3, path: w('C:', 'x', 'c.exe') },
    ],
    killVerified: async (pid) => {
      if (pid === 1) throw new Error('denied')
      killed.push(pid)
    },
    roots: ROOTS,
    log: (m) => logs.push(m),
  })
  assert.deepEqual(result, [1, 2])
  assert.deepEqual(killed, [2])
  assert.ok(logs.some((m) => m.includes('denied')))
  const failing = await lib.killOrphans({
    listProcesses: async () => {
      throw new Error('no powershell')
    },
    killVerified: async () => {},
    roots: ROOTS,
  })
  assert.deepEqual(failing, [])
})

test('shouldAutoRetry retries twice and then gives up', () => {
  assert.deepEqual([1, 2, 3].map(lib.shouldAutoRetry), [true, true, false])
})

test('splashScript escapes text and picks a known state', () => {
  const script = lib.splashScript({ kind: 'error', title: 'a"b', detail: '</script>' })
  assert.match(script, /dataset\.state = "error"/)
  assert.ok(script.includes(JSON.stringify('a"b')))
  assert.match(lib.splashScript({ kind: 'weird' }), /dataset\.state = "starting"/)
  assert.match(lib.startingDetail(2, 5), /попытка 2.*5 с/)
})

test('trimLog keeps the tail on a line boundary and leaves small logs alone', () => {
  const lines = Array.from({ length: 100 }, (_, i) => `line ${i}`).join('\n') + '\n'
  assert.equal(lib.trimLog('short\n', 1000), 'short\n')
  const trimmed = lib.trimLog(lines, 200)
  assert.ok(Buffer.byteLength(trimmed) <= 200)
  assert.ok(trimmed.endsWith('line 99\n'))
  assert.match(trimmed, /^line \d+\n/)
})

test('createLog appends lines and keeps the file under the limit', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nt-log-'))
  try {
    const file = path.join(dir, 'electron.log')
    const log = lib.createLog(file, { maxBytes: 500, now: () => new Date(0) })
    log('start')
    assert.equal(fs.readFileSync(file, 'utf8'), '1970-01-01T00:00:00.000Z start\n')
    for (let i = 0; i < 100; i += 1) log(`message ${i}`)
    assert.ok(fs.statSync(file).size <= 500)
    assert.ok(fs.readFileSync(file, 'utf8').includes('message 99'))
    fs.writeFileSync(file, 'x\n'.repeat(1000))
    lib.createLog(file, { maxBytes: 500 })
    assert.ok(fs.statSync(file).size <= 500)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('parseProcessList keeps the creation time as a string', () => {
  const [item] = lib.parseProcessList(JSON.stringify({ ProcessId: 3, ExecutablePath: 'x', Created: '133800000000000001' }))
  assert.equal(item.created, '133800000000000001')
})

test('killOrphans passes the creation time so a reused pid is not killed blindly', async () => {
  const seen = []
  await lib.killOrphans({
    listProcesses: async () => [{ pid: 9, path: w(ROOTS[0], 'a.exe'), created: '42' }],
    killVerified: async (pid, created) => seen.push([pid, created]),
    roots: ROOTS,
  })
  assert.deepEqual(seen, [[9, '42']])
})

test('process scripts stay in the current session and use no taskkill tree flag', () => {
  assert.match(lib.LIST_PROCESSES_SCRIPT, /SessionId -eq \$s/)
  assert.match(lib.KILL_VERIFIED_SCRIPT, /NT_CREATED/)
  assert.doesNotMatch(lib.KILL_VERIFIED_SCRIPT, /taskkill/i)
})

test('systemExe builds absolute System32 paths with a fallback root', () => {
  assert.equal(lib.systemExe(w('D:', 'Win'), 'taskkill.exe'), w('D:', 'Win', 'System32', 'taskkill.exe'))
  assert.equal(lib.systemExe(undefined, 'a.exe'), w('C:', 'Windows', 'System32', 'a.exe'))
})
