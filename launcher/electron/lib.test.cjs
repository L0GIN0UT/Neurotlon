'use strict'
const assert = require('node:assert/strict')
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
