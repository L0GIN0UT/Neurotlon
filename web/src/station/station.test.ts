import { afterEach, describe, expect, it, vi } from 'vitest'
import { postCommand, readBridgeConfig, sendCommand } from './bridge.ts'
import { commandForKey, screenKey } from './flow.ts'
import { accentFor, hintsFor, initials, RESULT_STEP, stepOf } from './model.ts'
import { splitResultLine, STEPS } from './texts.ts'
import type { CandidateView, StateView } from './types.ts'

const candidate: CandidateView = {
  code: 'NT03',
  display_name: 'Анна',
  team: { number: 1, name: 'Красные', color: '#e5484d' },
  issues: [],
  offline: false,
  warned: false,
}
const idle: StateView = { kind: 'idle', input: '', notice: null, taken: [] }
const confirm: StateView = { kind: 'confirm', candidate, taken: [], notice: null, is_last: true }

describe('model', () => {
  it('maps every screen to a step of the bar', () => {
    expect(stepOf('idle')).toBe(0)
    expect(stepOf('checking')).toBe(0)
    expect(stepOf('confirm')).toBe(1)
    expect(stepOf('starting')).toBe(2)
    expect(stepOf('calibrating')).toBe(2)
    expect(stepOf('playing')).toBe(3)
    expect(stepOf('problem')).toBe(3)
    expect(stepOf('done')).toBe(4)
    expect(stepOf('done')).toBe(STEPS.length - 1)
    expect(stepOf('done')).toBe(RESULT_STEP)
    expect(stepOf('blocked')).toBeNull()
    expect(stepOf('rejected')).toBeNull()
  })

  it('gives each discipline its own accent and a fallback', () => {
    expect(new Set(['darts', 'football', 'pong'].map(accentFor)).size).toBe(3)
    expect(accentFor('unknown')).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('takes the initial of the name, else the digits of the code', () => {
    expect(initials('анна', 'NT03')).toBe('А')
    expect(initials(null, 'NT07')).toBe('07')
    expect(initials('  ', 'NT07')).toBe('07')
    expect(initials(null, 'XY')).toBe('XY')
  })

  it('hints "Play" only for the last player', () => {
    expect(hintsFor(confirm)[0]).toEqual(['Enter', 'Играть'])
    expect(hintsFor({ ...confirm, is_last: false })[0]).toEqual(['Enter', 'Дальше'])
    expect(hintsFor({ kind: 'playing', players: [], offline: false, default_limit: false })).toEqual([])
  })
})

describe('keys', () => {
  it('types digits and letters on the scan screen, ignores other keys', () => {
    expect(commandForKey(idle, '7')).toEqual({ action: 'type_char', value: '7' })
    expect(commandForKey(idle, 'n')).toEqual({ action: 'type_char', value: 'n' })
    expect(commandForKey(idle, 'Enter')).toEqual({ action: 'submit_input' })
    expect(commandForKey(idle, 'Backspace')).toEqual({ action: 'backspace' })
    expect(commandForKey(idle, 'Escape')).toEqual({ action: 'cancel' })
    expect(commandForKey(idle, 'F2')).toEqual({ action: 'show_rejected' })
    expect(commandForKey(idle, 'Shift')).toBeNull()
    expect(commandForKey(idle, ' ')).toBeNull()
  })

  it('confirms with Enter and cancels with Escape', () => {
    expect(commandForKey(confirm, 'Enter')).toEqual({ action: 'confirm' })
    expect(commandForKey(confirm, 'Escape')).toEqual({ action: 'cancel' })
    expect(commandForKey(confirm, '7')).toBeNull()
  })

  it('never gives up a session from the keyboard', () => {
    const problem: StateView = { kind: 'problem', reason: 'x', players: [] }
    expect(commandForKey(problem, 'Enter')).toEqual({ action: 'retry' })
    expect(commandForKey(problem, 'Escape')).toBeNull()
  })

  it('opens exports and closes the rejected list', () => {
    const rejected: StateView = { kind: 'rejected', items: [], exported_to: null }
    expect(commandForKey(rejected, 'e')).toEqual({ action: 'export_rejected' })
    expect(commandForKey(rejected, 'Escape')).toEqual({ action: 'close_rejected' })
  })

  it('re-animates only when the screen changes, not while typing', () => {
    expect(screenKey({ ...idle, input: '1' })).toBe(screenKey(idle))
    expect(screenKey(confirm)).toBe('confirm-NT03')
    expect(screenKey({ ...confirm, candidate: { ...candidate, code: 'NT14' } })).toBe('confirm-NT14')
  })
})

describe('bridge', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('prefers the Electron preload config over the address', () => {
    const fromElectron = { url: 'http://127.0.0.1:1', token: 'a' }
    const win = { stationBridge: fromElectron, location: { search: '?port=9999&token=b' } }
    expect(readBridgeConfig(win as unknown as Window)).toEqual(fromElectron)
  })

  it('reads port and token from the address in the browser', () => {
    const win = { location: { search: '?port=8799&token=abc' } }
    expect(readBridgeConfig(win as unknown as Window)).toEqual({
      url: 'http://127.0.0.1:8799',
      token: 'abc',
    })
  })

  it('rejects a missing or malformed port and a missing token', () => {
    for (const search of ['', '?port=8799', '?token=a', '?port=http://evil&token=a', '?port=1&token=a']) {
      expect(readBridgeConfig({ location: { search } } as unknown as Window)).toBeNull()
    }
  })

  it('posts the command with the token header and reports failures', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true }).mockRejectedValueOnce(new Error('down'))
    vi.stubGlobal('fetch', fetchMock)
    const config = { url: 'http://127.0.0.1:8799', token: 'secret' }
    expect(await sendCommand(config, { action: 'type_char', value: '7' })).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8799/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Station-Token': 'secret' },
      body: JSON.stringify({ action: 'type_char', value: '7' }),
    })
    expect(await sendCommand(config, { action: 'cancel' })).toBe(false)
  })
})

describe('postCommand', () => {
  afterEach(() => vi.unstubAllGlobals())
  const config = { url: 'http://127.0.0.1:8799', token: 'secret' }
  const refuse = (json: () => Promise<unknown>) =>
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json }))

  it('returns the text the launcher sends in the 400 body', async () => {
    refuse(() => Promise.resolve({ error: 'Введите токен станции' }))
    expect(await postCommand(config, { action: 'cancel' })).toEqual({ ok: false, error: 'Введите токен станции' })
  })

  it('has no text when the body is empty, not JSON, or has no error string', async () => {
    refuse(() => Promise.reject(new Error('no body')))
    expect(await postCommand(config, { action: 'cancel' })).toEqual({ ok: false, error: null })
    refuse(() => Promise.resolve({ error: 5 }))
    expect(await postCommand(config, { action: 'cancel' })).toEqual({ ok: false, error: null })
    refuse(() => Promise.resolve({ error: '  ' }))
    expect(await postCommand(config, { action: 'cancel' })).toEqual({ ok: false, error: null })
  })

  it('reports success without an error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
    expect(await postCommand(config, { action: 'cancel' })).toEqual({ ok: true, error: null })
  })
})

describe('texts', () => {
  it('splits a result line into label and value', () => {
    expect(splitResultLine('NT03: 8 очк.')).toEqual({ label: 'NT03', value: '8 очк.' })
    expect(splitResultLine('Отмечено: не пройдено')).toEqual({ label: 'Отмечено', value: 'не пройдено' })
    expect(splitResultLine('Без значения')).toEqual({ label: 'Без значения', value: '' })
  })
})
