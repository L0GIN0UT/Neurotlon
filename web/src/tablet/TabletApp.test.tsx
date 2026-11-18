import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { Discipline, Eligibility, Me, ResultSubmission } from './api.ts'
import { memoryStore } from './offlineQueue.ts'
import { TabletApp } from './TabletApp.tsx'

type Handler = (body: unknown) => Response | Promise<Response>

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function problem(status: number, code: string): Response {
  return json({ type: 'about:blank', title: code, status, code }, status)
}

interface Server {
  fetchFn: typeof fetch
  routes: Map<string, Handler>
  calls: { key: string; body: unknown }[]
  bodies: (key: string) => unknown[]
}

function createServer(discipline: Discipline, role: Me['role'] = 'volunteer'): Server {
  const routes = new Map<string, Handler>()
  const calls: Server['calls'] = []
  let loggedIn = false
  routes.set('POST /auth/login', () => {
    loggedIn = true
    return new Response(null, { status: 204 })
  })
  routes.set('GET /auth/me', () =>
    loggedIn
      ? json({ login: 'vol', role, discipline: role === 'volunteer' ? discipline : null })
      : problem(401, 'unauthorized'),
  )
  routes.set('GET /me/config', () =>
    json({
      discipline,
      section: 'physical',
      duration_s: 120,
      max_points: discipline === 'pong' ? null : 10,
    }),
  )
  routes.set('POST /results', (body) => {
    const payload = body as ResultSubmission
    return json(
      {
        session_id: payload.session_id,
        results: payload.entries.map((e, i) => ({
          id: i + 1,
          participant_code: e.participant_code,
          status: 'confirmed',
        })),
        warnings: [],
      },
      201,
    )
  })
  const fetchFn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'https://hall.local')
    const path = url.pathname.replace('/api/v1', '')
    let key = `${init?.method ?? 'GET'} ${path}`
    const body: unknown = init?.body ? JSON.parse(String(init.body)) : undefined
    if (path.startsWith('/participants/')) key = `GET /participants/*`
    if (/^\/results\/.+\/undo$/.test(path)) key = 'POST /results/*/undo'
    calls.push({ key, body })
    const handler = routes.get(key)
    if (!handler) return Promise.resolve(problem(404, 'not_found'))
    return Promise.resolve(handler(body))
  }) as unknown as typeof fetch
  return {
    fetchFn,
    routes,
    calls,
    bodies: (key) => calls.filter((c) => c.key === key).map((c) => c.body),
  }
}

function eligibility(code: string, issues: Eligibility['issues'] = []): Eligibility {
  return {
    code,
    display_name: null,
    team: { number: 1, name: 'Альфа', color: '#aa00bb' },
    issues,
  }
}

function setEligibility(server: Server, issuesByCode: Record<string, Eligibility['issues']> = {}) {
  server.routes.set('GET /participants/*', () => json(eligibility('NT07', issuesByCode.NT07)))
}

async function login() {
  fireEvent.change(await screen.findByLabelText('Логин'), { target: { value: 'vol' } })
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: 'Войти' }))
}

async function addParticipant(label: string, value: string) {
  fireEvent.change(await screen.findByLabelText(label), { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: 'Добавить' }))
}

function enterPoints(value: string) {
  fireEvent.change(screen.getByLabelText('Очки за секцию'), { target: { value } })
}

function renderApp(server: Server, store = memoryStore()) {
  render(<TabletApp fetchFn={server.fetchFn} store={store} />)
  return store
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('login', () => {
  test('shows the login form when there is no session and rejects a wrong password', async () => {
    const server = createServer('darts')
    server.routes.set('POST /auth/login', () => problem(401, 'unauthorized'))
    renderApp(server)
    await login()
    expect(await screen.findByText('Неверный логин или пароль')).toBeDefined()
  })

  test('other roles see a message instead of the tablet', async () => {
    const server = createServer('darts', 'judge')
    renderApp(server)
    await login()
    expect(await screen.findByText('Только для волонтёров')).toBeDefined()
    expect(screen.queryByText('Участник')).toBeNull()
  })

  test('a 401 in the middle of work returns to login', async () => {
    const server = createServer('darts')
    server.routes.set('GET /participants/*', () => problem(401, 'unauthorized'))
    renderApp(server)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(await screen.findByRole('button', { name: 'Далее' }))
    expect(await screen.findByLabelText('Логин')).toBeDefined()
  })
})

describe('darts flow', () => {
  test('scan by manual input, warnings, section points, summary, record, undo', async () => {
    const server = createServer('darts')
    setEligibility(server, { NT07: ['already_completed', 'no_pair_assigned'] })
    server.routes.set('POST /results/*/undo', () => new Response(null, { status: 204 }))
    renderApp(server)
    await login()

    expect(await screen.findByRole('heading', { name: 'Участник' })).toBeDefined()
    await addParticipant('ID участника', '7')
    expect(screen.getByText('NT07')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))

    expect(await screen.findByText('Эту секцию участник уже проходил')).toBeDefined()
    expect(screen.getByText('Участнику не назначена пара')).toBeDefined()
    expect(screen.getByText(/Альфа/)).toBeDefined()
    expect(document.body.textContent).not.toMatch(/ОВЗ|категори/i)
    fireEvent.click(screen.getByRole('button', { name: 'Продолжить' }))

    expect(await screen.findByRole('heading', { name: 'Ввод результата' })).toBeDefined()
    expect(screen.getByRole('timer').textContent).toContain('2:00')
    expect(screen.queryByLabelText('Бросок')).toBeNull()
    expect(screen.getByText('Целое число от 0 до 10')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Увеличить очки за секцию на 1' }))
    fireEvent.click(screen.getByRole('button', { name: 'Увеличить очки за секцию на 1' }))
    expect((screen.getByLabelText('Очки за секцию') as HTMLInputElement).value).toBe('2')
    fireEvent.click(screen.getByRole('button', { name: 'Уменьшить очки за секцию на 1' }))
    expect((screen.getByLabelText('Очки за секцию') as HTMLInputElement).value).toBe('1')
    enterPoints('7')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))

    expect(await screen.findByText('Очки: 7')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Записать' }))
    expect(await screen.findByRole('heading', { name: 'Записано' })).toBeDefined()

    const [sent] = server.bodies('POST /results') as ResultSubmission[]
    expect(sent).toMatchObject({
      discipline: 'darts',
      section: 'physical',
      entries: [{ participant_code: 'NT07', outcome: 'completed', points: 7 }],
    })
    expect(sent?.session_id).toMatch(/^[0-9a-f-]{36}$/)

    fireEvent.click(screen.getByRole('button', { name: /Отменить/ }))
    expect(await screen.findByText('Результат отменён.')).toBeDefined()
    expect(server.calls.some((c) => c.key === 'POST /results/*/undo')).toBe(true)
  })

  test('after 30 s undo is replaced by a correction request', async () => {
    const server = createServer('darts')
    setEligibility(server)
    server.routes.set('POST /corrections', () => json({ id: 1 }, 201))
    renderApp(server)
    await login()
    await addParticipant('ID участника', 'NT07')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
    enterPoints('10')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))
    await screen.findByRole('heading', { name: 'Записано' })
    expect(screen.getByRole('button', { name: /Отменить/ })).toBeDefined()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000)
    })

    expect(screen.queryByRole('button', { name: /Отменить/ })).toBeNull()
    fireEvent.change(screen.getByLabelText('Что исправить'), { target: { value: 'Не те очки' } })
    fireEvent.click(screen.getByRole('button', { name: 'Запрос судье на исправление' }))
    expect(await screen.findByText('Запрос отправлен судье.')).toBeDefined()
    const [sent] = server.bodies('POST /results') as ResultSubmission[]
    expect(server.bodies('POST /corrections')).toEqual([
      { session_id: sent?.session_id, comment: 'Не те очки' },
    ])
  })

  test('a 409 from undo switches to the correction request', async () => {
    const server = createServer('darts')
    setEligibility(server)
    server.routes.set('POST /results/*/undo', () => problem(409, 'conflict'))
    renderApp(server)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
    enterPoints('10')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))
    fireEvent.click(await screen.findByRole('button', { name: /Отменить/ }))
    expect(await screen.findByLabelText('Что исправить')).toBeDefined()
  })

  test('the same session_id is reused when the volunteer goes back and records again', async () => {
    const server = createServer('darts')
    setEligibility(server)
    let first = true
    server.routes.set('POST /results', (body) => {
      if (first) {
        first = false
        return problem(500, 'internal')
      }
      return json(
        { session_id: (body as ResultSubmission).session_id, results: [], warnings: [] },
        200,
      )
    })
    renderApp(server)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
    enterPoints('10')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))
    // 500: результат ушёл в очередь, затем успешно отправляется тем же session_id
    expect(await screen.findByRole('heading', { name: 'В очереди' })).toBeDefined()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000)
    })
    const sent = server.bodies('POST /results') as ResultSubmission[]
    expect(sent).toHaveLength(2)
    expect(sent[1]?.session_id).toBe(sent[0]?.session_id)
  })
})

describe('section points limit', () => {
  async function toEntry(server: Server) {
    setEligibility(server)
    renderApp(server)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
  }

  test('points above the limit are refused with a clear message and nothing is sent', async () => {
    const server = createServer('darts')
    await toEntry(server)
    enterPoints('10.5')
    expect(screen.getAllByText('Очки за секцию — целое число от 0 до 10').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    expect(await screen.findByRole('alert')).toBeDefined()
    expect(screen.getByRole('heading', { name: 'Ввод результата' })).toBeDefined()
    expect(server.bodies('POST /results')).toEqual([])
  })

  test('the plus button stops at the limit and the minus button at zero', async () => {
    const server = createServer('darts')
    await toEntry(server)
    const field = screen.getByLabelText('Очки за секцию') as HTMLInputElement
    fireEvent.click(screen.getByRole('button', { name: 'Уменьшить очки за секцию на 1' }))
    expect(field.value).toBe('0')
    enterPoints('10')
    fireEvent.click(screen.getByRole('button', { name: 'Увеличить очки за секцию на 1' }))
    expect(field.value).toBe('10')
    expect(field.max).toBe('10')
    expect(field.step).toBe('1')
  })

  test('an empty field needs points, and exactly the limit is recorded', async () => {
    const server = createServer('football')
    await toEntry(server)
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    expect(await screen.findByText('Введите очки за секцию')).toBeDefined()
    enterPoints('10')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))
    await screen.findByRole('heading', { name: 'Записано' })
    expect((server.bodies('POST /results') as ResultSubmission[])[0]?.entries).toEqual([
      { participant_code: 'NT07', outcome: 'completed', points: 10 },
    ])
  })

  test('a cached config without max_points still works', async () => {
    const server = createServer('darts')
    server.routes.set('GET /me/config', () =>
      json({ discipline: 'darts', section: 'physical', duration_s: 120 }),
    )
    await toEntry(server)
    expect((screen.getByLabelText('Очки за секцию') as HTMLInputElement).max).toBe('1000')
  })
})

describe('football flow', () => {
  test('one section points field replaces elements and accuracy', async () => {
    const server = createServer('football')
    setEligibility(server)
    renderApp(server)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
    expect(screen.queryByRole('button', { name: /Элемент 1/ })).toBeNull()
    expect(screen.queryByLabelText('Очки за точность')).toBeNull()
    enterPoints('8')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    expect(await screen.findByText('Очки: 8')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Записать' }))
    await screen.findByRole('heading', { name: 'Записано' })
    expect((server.bodies('POST /results') as ResultSubmission[])[0]?.entries).toEqual([
      { participant_code: 'NT07', outcome: 'completed', points: 8 },
    ])
  })
})

describe('not completed', () => {
  test('sends reason and comment without points', async () => {
    const server = createServer('darts')
    setEligibility(server)
    renderApp(server)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
    fireEvent.click(screen.getByRole('button', { name: 'Не пройдено' }))
    fireEvent.change(screen.getByLabelText('Причина'), { target: { value: 'health' } })
    fireEvent.change(screen.getByLabelText('Комментарий (необязательно)'), {
      target: { value: 'Голова' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    expect(await screen.findByText(/Не пройдено: Самочувствие \(Голова\)/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Записать' }))
    await screen.findByRole('heading', { name: 'Записано' })
    expect((server.bodies('POST /results') as ResultSubmission[])[0]?.entries).toEqual([
      { participant_code: 'NT07', outcome: 'not_completed', reason: 'health', comment: 'Голова' },
    ])
  })
})

describe('pong flow', () => {
  test('needs two players, one winner, and sends wins', async () => {
    const server = createServer('pong')
    server.routes.set('GET /participants/*', () => json(eligibility('NT03')))
    renderApp(server)
    await login()

    await addParticipant('ID игрока', '3')
    expect((screen.getByRole('button', { name: 'Далее' }) as HTMLButtonElement).disabled).toBe(true)
    await addParticipant('ID игрока', 'NT14')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })

    const points = screen.getAllByLabelText('Очки')
    fireEvent.change(points[0] as HTMLElement, { target: { value: '7' } })
    fireEvent.change(points[1] as HTMLElement, { target: { value: '11' } })
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    expect(await screen.findByText('Выберите победителя')).toBeDefined()

    fireEvent.click(screen.getByRole('button', { name: 'Победил NT14' }))
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))
    await screen.findByRole('heading', { name: 'Записано' })

    expect((server.bodies('POST /results') as ResultSubmission[])[0]?.entries).toEqual([
      { participant_code: 'NT03', outcome: 'completed', points: 7, wins: 0 },
      { participant_code: 'NT14', outcome: 'completed', points: 11, wins: 1 },
    ])
  })
})

describe('offline', () => {
  test('a network failure queues the result and it is sent when the network is back', async () => {
    const server = createServer('darts')
    setEligibility(server)
    const online = server.routes.get('POST /results') as Handler
    let networkUp = false
    const realFetch = server.fetchFn
    const fetchFn = ((input: RequestInfo | URL, init?: RequestInit) => {
      if (!networkUp && String(input).endsWith('/results') && init?.method === 'POST') {
        return Promise.reject(new TypeError('Failed to fetch'))
      }
      return realFetch(input, init)
    }) as typeof fetch
    const store = memoryStore()
    render(<TabletApp fetchFn={fetchFn} store={store} />)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
    enterPoints('10')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))

    expect(await screen.findByRole('heading', { name: 'В очереди' })).toBeDefined()
    expect(screen.getByText('В очереди: 1')).toBeDefined()
    const queued = await store.list()
    expect(queued).toHaveLength(1)
    expect(queued[0]?.payload.entries[0]?.points).toBe(10)

    networkUp = true
    server.routes.set('POST /results', online)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000)
    })
    await waitFor(() => expect(screen.queryByText('В очереди: 1')).toBeNull())
    expect(await store.list()).toEqual([])
    expect(server.bodies('POST /results')).toHaveLength(1)
  })

  test('a 409 on resend moves the result to the errors list', async () => {
    const server = createServer('darts')
    setEligibility(server)
    let call = 0
    server.routes.set('POST /results', () => {
      call += 1
      return call === 1 ? new Response('down', { status: 503 }) : problem(409, 'session_conflict')
    })
    const store = renderApp(server)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
    enterPoints('10')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))
    expect(await screen.findByText('В очереди: 1')).toBeDefined()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000)
    })
    const errors = await screen.findByRole('button', { name: 'Ошибки: 1' })
    expect(screen.queryByText('В очереди: 1')).toBeNull()
    fireEvent.click(errors)
    const list = screen.getByRole('list', { name: 'Ошибки отправки' })
    expect(within(list).getByText(/NT07/)).toBeDefined()
    expect(within(list).getByText(/другими данными/)).toBeDefined()
    expect((await store.list())[0]?.state).toBe('failed')
  })

  test('a server rejection on direct send shows the error and keeps it in the list', async () => {
    const server = createServer('darts')
    setEligibility(server)
    server.routes.set('POST /results', () => problem(422, 'invalid_entries'))
    renderApp(server)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
    await screen.findByRole('heading', { name: 'Ввод результата' })
    enterPoints('10')
    fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))
    expect(await screen.findByText(/Сервер отклонил результат/)).toBeDefined()
    expect(await screen.findByRole('button', { name: 'Ошибки: 1' })).toBeDefined()
  })

  test('eligibility without network warns but does not block', async () => {
    const server = createServer('darts')
    const realFetch = server.fetchFn
    const fetchFn = ((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes('/eligibility')
        ? Promise.reject(new TypeError('Failed to fetch'))
        : realFetch(input, init)) as typeof fetch
    render(<TabletApp fetchFn={fetchFn} store={memoryStore()} />)
    await login()
    await addParticipant('ID участника', '7')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    expect(await screen.findByText(/проверка пропущена/)).toBeDefined()
    const next = screen.getByRole('button', { name: 'Продолжить' }) as HTMLButtonElement
    expect(next.disabled).toBe(false)
  })

  test('an unknown participant blocks continuing', async () => {
    const server = createServer('darts')
    server.routes.set('GET /participants/*', () => problem(404, 'unknown_participant'))
    renderApp(server)
    await login()
    await addParticipant('ID участника', '19')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    expect(await screen.findByText('Участник с таким ID не найден')).toBeDefined()
    expect((screen.getByRole('button', { name: 'Продолжить' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
  })
})

async function recordDarts(server: Server) {
  setEligibility(server)
  await addParticipant('ID участника', '7')
  fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))
  await screen.findByRole('heading', { name: 'Ввод результата' })
  enterPoints('10')
  fireEvent.click(screen.getByRole('button', { name: 'К сводке' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Записать' }))
}

describe('queue ownership and storage', () => {
  test('logout asks for confirmation while records are unsent', async () => {
    const server = createServer('darts')
    server.routes.set('POST /results', () => new Response('down', { status: 503 }))
    server.routes.set('POST /auth/logout', () => new Response(null, { status: 204 }))
    renderApp(server)
    await login()
    await recordDarts(server)
    await screen.findByText('В очереди: 1')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByRole('button', { name: 'Выйти' }))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(screen.queryByLabelText('Логин')).toBeNull()
    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Выйти' }))
    expect(await screen.findByLabelText('Логин')).toBeDefined()
    confirm.mockRestore()
  })

  test('records of another login are shown, not sent', async () => {
    const server = createServer('darts')
    const store = memoryStore()
    await store.put({
      sessionId: '11111111-1111-4111-8111-111111111111',
      payload: {
        session_id: '11111111-1111-4111-8111-111111111111',
        discipline: 'darts',
        section: 'physical',
        finished_at: '2027-04-12T07:05:00.000Z',
        entries: [{ participant_code: 'NT05', outcome: 'completed', points: 3 }],
      },
      queuedAt: '2027-04-12T07:05:00.000Z',
      state: 'pending',
      login: 'ann',
    })
    renderApp(server, store)
    await login()
    expect(await screen.findByText(/войдите под ann/)).toBeDefined()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(server.bodies('POST /results')).toEqual([])
    expect(await store.list()).toHaveLength(1)
  })

  test('a voided session on resend lands in errors with a clear text', async () => {
    const server = createServer('darts')
    let call = 0
    server.routes.set('POST /results', () => {
      call += 1
      return call === 1 ? new Response('down', { status: 503 }) : problem(409, 'result_voided')
    })
    renderApp(server)
    await login()
    await recordDarts(server)
    await screen.findByText('В очереди: 1')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000)
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Ошибки: 1' }))
    const list = screen.getByRole('list', { name: 'Ошибки отправки' })
    expect(within(list).getByText(/уже отменена/)).toBeDefined()
  })

  test('a storage failure is reported as not saved and can be retried', async () => {
    const server = createServer('darts')
    server.routes.set('POST /results', () => new Response('down', { status: 503 }))
    const store = memoryStore()
    store.put = () => Promise.reject(new DOMException('quota', 'QuotaExceededError'))
    renderApp(server, store)
    await login()
    await recordDarts(server)
    expect(await screen.findByText(/Не сохранено/)).toBeDefined()
    expect(screen.getByRole('button', { name: 'Записать' })).toBeDefined()
    expect(screen.queryByText('В очереди: 1')).toBeNull()
  })
})

describe('participant input', () => {
  test('rejects text that is not an ID', async () => {
    const server = createServer('darts')
    renderApp(server)
    await login()
    await addParticipant('ID участника', 'привет')
    expect(await screen.findByText(/Это не ID участника/)).toBeDefined()
    expect((screen.getByRole('button', { name: 'Далее' }) as HTMLButtonElement).disabled).toBe(true)
  })

  test('without a camera the scanner explains and manual input stays', async () => {
    const server = createServer('darts')
    renderApp(server)
    await login()
    fireEvent.click(await screen.findByRole('button', { name: 'Сканировать QR' }))
    expect(await screen.findByText('Камера недоступна. Введите ID вручную.')).toBeDefined()
    expect(screen.getByLabelText('ID участника')).toBeDefined()
  })
})
