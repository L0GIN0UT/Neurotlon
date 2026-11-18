import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, test } from 'vitest'
import { buildServiceWorker, hashPublicFiles } from './sw-plugin.ts'

const dirs: string[] = []

function publicDir(manifest: string): string {
  const dir = mkdtempSync(join(tmpdir(), 'nt-public-'))
  dirs.push(dir)
  writeFileSync(join(dir, 'manifest.webmanifest'), manifest)
  writeFileSync(join(dir, 'icon.svg'), '<svg/>')
  writeFileSync(join(dir, 'favicon.svg'), '<svg/>')
  return dir
}

afterEach(() => {
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true })
})

test('caches navigation responses only when they are ok and basic', () => {
  const source = buildServiceWorker(['/'], 'x')
  expect(source).toContain("response.ok && response.type === 'basic'")
  const guard = source.indexOf("response.type === 'basic'")
  expect(source.indexOf("cache.put('/'")).toBeGreaterThan(guard)
})

test('the cache version changes when a public file changes', () => {
  const files = ['/', '/assets/a.js']
  const before = buildServiceWorker(files, hashPublicFiles(publicDir('{"a":1}')))
  const same = buildServiceWorker(files, hashPublicFiles(publicDir('{"a":1}')))
  const after = buildServiceWorker(files, hashPublicFiles(publicDir('{"a":2}')))
  expect(same).toBe(before)
  expect(after).not.toBe(before)
})

test('the cache version changes when the build files change', () => {
  const hash = hashPublicFiles(publicDir('{}'))
  expect(buildServiceWorker(['/', '/assets/a.js'], hash)).not.toBe(
    buildServiceWorker(['/', '/assets/b.js'], hash),
  )
})
