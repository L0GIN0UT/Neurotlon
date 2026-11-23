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
  })
  assert.deepEqual(lib.parseArgs([]), { config: null, windowed: false, dev: false })
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
