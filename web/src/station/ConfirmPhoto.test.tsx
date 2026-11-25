import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { photoSrc } from './bridge.ts'
import { StationApp } from './StationApp.tsx'
import type { CandidateView, Snapshot, StateView } from './types.ts'

class FakeEventSource {
  static last: FakeEventSource | null = null
  static readonly CLOSED = 2
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  readyState = 1
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.last = this
  }
  close(): void {
    this.readyState = FakeEventSource.CLOSED
  }
  emit(snapshot: Snapshot): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(snapshot) }))
  }
}

const player = (code: string, extra: Partial<CandidateView> = {}): CandidateView => ({
  code,
  display_name: 'Анна',
  team: { number: 1, name: 'Красные', color: '#e5484d' },
  issues: [],
  offline: false,
  warned: false,
  ...extra,
})

function confirm(candidate: CandidateView, taken: CandidateView[] = [], discipline = 'darts') {
  const state: StateView = { kind: 'confirm', candidate, taken, notice: null, is_last: true }
  act(() =>
    FakeEventSource.last?.emit({
      discipline,
      players_needed: discipline === 'pong' ? 2 : 1,
      status: { pending: 0, rejected: 0, online: true },
      state,
    }),
  )
}

describe('player photo on the confirmation screen', () => {
  beforeEach(() => {
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
    window.history.pushState({}, '', '/station.html?port=8799&token=abcdefgh')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    FakeEventSource.last = null
  })

  it('shows the photo with the window token and an alt without the name', async () => {
    render(<StationApp />)
    confirm(player('NT03', { photo_url: '/api/photo/NT03?v=1700' }))
    const img = await screen.findByTestId('avatar-photo')
    expect(img.getAttribute('src')).toBe('http://127.0.0.1:8799/api/photo/NT03?v=1700&token=abcdefgh')
    expect(img.getAttribute('alt')).toBe('Фото участника NT03')
    expect(img.getAttribute('alt')).not.toContain('Анна')
  })

  it('keeps the letter while the photo loads, then the photo is shown', async () => {
    render(<StationApp />)
    confirm(player('NT03', { photo_url: '/api/photo/NT03?v=1' }))
    const img = await screen.findByTestId('avatar-photo')
    expect(screen.getByText('А')).toBeTruthy()
    expect(img.className).not.toContain('avatar-photo-ready')
    fireEvent.load(img)
    expect(img.className).toContain('avatar-photo-ready')
  })

  it('falls back to the letter when there is no photo', async () => {
    render(<StationApp />)
    confirm(player('NT03', { photo_url: null }))
    expect(await screen.findByText('А')).toBeTruthy()
    expect(screen.queryByTestId('avatar-photo')).toBeNull()
  })

  it('falls back to the letter for an older core without the field', async () => {
    render(<StationApp />)
    confirm(player('NT03'))
    expect(await screen.findByText('А')).toBeTruthy()
    expect(screen.queryByTestId('avatar-photo')).toBeNull()
  })

  it('falls back to the letter when the photo fails to load', async () => {
    render(<StationApp />)
    confirm(player('NT03', { photo_url: '/api/photo/NT03?v=1' }))
    fireEvent.error(await screen.findByTestId('avatar-photo'))
    expect(screen.queryByTestId('avatar-photo')).toBeNull()
    expect(screen.getByText('А')).toBeTruthy()
  })

  it('tries again for a new photo version after a failure', async () => {
    render(<StationApp />)
    confirm(player('NT03', { photo_url: '/api/photo/NT03?v=1' }))
    fireEvent.error(await screen.findByTestId('avatar-photo'))
    confirm(player('NT03', { photo_url: '/api/photo/NT03?v=2' }))
    expect((await screen.findByTestId('avatar-photo')).getAttribute('src')).toContain('v=2')
  })

  it('shows each pong player own photo on his card', async () => {
    render(<StationApp />)
    const first = player('NT03', { photo_url: '/api/photo/NT03?v=1' })
    confirm(player('NT04', { photo_url: '/api/photo/NT04?v=5' }), [first], 'pong')
    const img = await screen.findByTestId('avatar-photo')
    expect(img.getAttribute('src')).toContain('/api/photo/NT04?v=5')
    expect(img.getAttribute('alt')).toBe('Фото участника NT04')
  })

  it('shows the mismatch notice text for a not_opponents issue', async () => {
    render(<StationApp />)
    confirm(player('NT04', { issues: ['not_opponents'], warned: true }))
    expect(await screen.findByText('Не соперник по сетке')).toBeTruthy()
  })
})

describe('photoSrc', () => {
  const config = { url: 'http://127.0.0.1:1', token: 'a b' }
  it('adds the token to the query', () => {
    expect(photoSrc(config, '/api/photo/NT01')).toBe('http://127.0.0.1:1/api/photo/NT01?token=a%20b')
  })
  it('refuses foreign or empty links', () => {
    expect(photoSrc(config, null)).toBeNull()
    expect(photoSrc(config, undefined)).toBeNull()
    expect(photoSrc(config, 'https://evil.example/x.jpg')).toBeNull()
    expect(photoSrc(config, '//evil.example/api/photo/NT01')).toBeNull()
  })
})
