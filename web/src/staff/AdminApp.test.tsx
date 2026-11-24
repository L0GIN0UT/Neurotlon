import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { createFakeServer, json, problem } from '../test/fakeServer.ts'
import type { FakeServer } from '../test/fakeServer.ts'
import { AdminApp } from './AdminApp.tsx'
import { BADGES_URL } from './api.ts'
import type { Participant, StationInfo, UserInfo } from './api.ts'

function person(code: string, extra: Partial<Participant> = {}): Participant {
  return {
    code,
    display_name: null,
    checked_in: false,
    checked_in_at: null,
    team: null,
    category: null,
    ...extra,
  }
}

function renderAdmin(server: FakeServer) {
  return render(<AdminApp fetchFn={server.fetchFn} />)
}

async function openTab(name: string) {
  fireEvent.click(await screen.findByRole('tab', { name }))
}

describe('вход и роли', () => {
  test('без сессии показывает вход и пускает админа', async () => {
    const server = createFakeServer(null)
    server.routes.set('GET /participants', () => json([]))
    renderAdmin(server)
    fireEvent.change(await screen.findByLabelText('Логин'), { target: { value: 'boss' } })
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'secret' } })
    // после входа сервер отвечает как для админа
    server.routes.set('GET /auth/me', () => json({ login: 'boss', role: 'admin', discipline: null }))
    fireEvent.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByRole('tab', { name: 'Участники' })).toBeDefined()
    expect(server.bodies('POST /auth/login')).toEqual([{ login: 'boss', password: 'secret' }])
  })

  test('неверный пароль показывает ошибку', async () => {
    const server = createFakeServer(null)
    server.routes.set('POST /auth/login', () => problem(401, 'unauthorized'))
    renderAdmin(server)
    fireEvent.change(await screen.findByLabelText('Логин'), { target: { value: 'boss' } })
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'bad' } })
    fireEvent.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByText('Неверный логин или пароль')).toBeDefined()
  })

  test('судье админка закрыта', async () => {
    const server = createFakeServer('judge', 'judy')
    renderAdmin(server)
    expect(await screen.findByRole('heading', { name: 'Нет доступа' })).toBeDefined()
    expect(screen.queryByRole('tab')).toBeNull()
  })

  test('вкладка «Пользователи» скрыта у админа и видна суперпользователю', async () => {
    const admin = createFakeServer('admin')
    admin.routes.set('GET /participants', () => json([]))
    const first = renderAdmin(admin)
    await screen.findByRole('tab', { name: 'Участники' })
    expect(screen.queryByRole('tab', { name: 'Пользователи' })).toBeNull()
    first.unmount()

    const root = createFakeServer('superuser', 'root')
    root.routes.set('GET /participants', () => json([]))
    renderAdmin(root)
    expect(await screen.findByRole('tab', { name: 'Пользователи' })).toBeDefined()
  })
})

describe('участники', () => {
  let server: FakeServer
  let people: Participant[]

  beforeEach(() => {
    server = createFakeServer('admin')
    people = [person('NT01'), person('NT02', { checked_in: true, checked_in_at: '2027-01-01T09:00:00Z', display_name: 'Аня' })]
    server.routes.set('GET /participants', () => json(people))
  })

  test('отметка о приходе: категория обязательна, имя необязательно', async () => {
    server.routes.set('POST /participants/*/check-in', (body) => {
      people[0] = person('NT01', { checked_in: true, display_name: (body as { display_name: string }).display_name || null })
      return json(people[0])
    })
    renderAdmin(server)
    fireEvent.click(await screen.findByRole('button', { name: 'Отметить NT01' }))
    const dialog = await screen.findByRole('dialog', { name: 'Отметка о приходе NT01' })
    const save = within(dialog).getByRole('button', { name: 'Сохранить' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)

    fireEvent.click(within(dialog).getByLabelText('Без ОВЗ'))
    fireEvent.change(within(dialog).getByLabelText('Имя для табло (необязательно)'), {
      target: { value: 'Борис' },
    })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(server.bodies('POST /participants/*/check-in')).toEqual([
      { category: 'general', display_name: 'Борис' },
    ])
    expect(await screen.findByRole('button', { name: 'Отменить отметку NT01' })).toBeDefined()
  })

  test('в списке видны баллы по дисциплинам и формам', async () => {
    server.routes.set('GET /disciplines', () =>
      json([
        { code: 'darts', game_duration_s: 240, physical_duration_s: 120, win_points: 3, max_section_points: 10 },
        { code: 'pong', game_duration_s: 240, physical_duration_s: 120, win_points: 3, max_section_points: 10 },
      ]),
    )
    const base = {
      session_id: 's', outcome: 'completed', reason: null, comment: null, status: 'confirmed',
      source: 'station', finished_at: '2027-01-01T10:00:00Z', version: 1, voided: false,
    }
    server.routes.set('GET /results', () =>
      json({
        total: 3,
        items: [
          { ...base, id: 1, participant_code: 'NT01', discipline: 'darts', section: 'bci', points: 7, wins: null },
          { ...base, id: 2, participant_code: 'NT01', discipline: 'darts', section: 'physical', points: 9, wins: null },
          { ...base, id: 3, participant_code: 'NT01', discipline: 'pong', section: 'bci', points: 21, wins: 1 },
        ],
      }),
    )
    renderAdmin(server)
    const row = (await screen.findByText('NT01')).closest('tr') as HTMLElement
    expect(await within(row).findByText('7 из 10')).toBeDefined()
    expect(within(row).getByText('9 из 10')).toBeDefined()
    expect(within(row).getByText('21 · победа')).toBeDefined()
  })

  test('поиск и фильтр сужают список', async () => {
    renderAdmin(server)
    await screen.findByText('NT01')
    fireEvent.click(screen.getByRole('button', { name: 'Пришли' }))
    expect(screen.queryByText('NT01')).toBeNull()
    expect(screen.getByText('NT02')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Все' }))
    fireEvent.change(screen.getByLabelText('Поиск'), { target: { value: 'аня' } })
    expect(screen.queryByText('NT01')).toBeNull()
    expect(screen.getByText('NT02')).toBeDefined()
  })

  test('табло открывается в новой вкладке', async () => {
    renderAdmin(server)
    const link = await screen.findByRole('link', { name: 'Табло' })
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(screen.getByRole('link', { name: 'Судья' }).getAttribute('target')).toBeNull()
  })

  test('в списке участников категории нет', async () => {
    people[1] = person('NT02', { checked_in: true, category: 'ovz' })
    renderAdmin(server)
    await screen.findByText('NT02')
    const text = document.body.textContent?.toLowerCase() ?? ''
    expect(text).not.toContain('овз')
    expect(text).not.toContain('ovz')
  })

  test('отмена отметки и смена имени', async () => {
    server.routes.set('DELETE /participants/*/check-in', () => json(person('NT02')))
    server.routes.set('PATCH /participants/*', (body) => json({ ...person('NT01'), ...(body as object) }))
    renderAdmin(server)
    fireEvent.click(await screen.findByRole('button', { name: 'Отменить отметку NT02' }))
    await waitFor(() => expect(server.count('DELETE /participants/*/check-in')).toBe(1))

    fireEvent.click(screen.getByRole('button', { name: 'Имя NT01' }))
    const dialog = await screen.findByRole('dialog', { name: 'Имя NT01' })
    expect(within(dialog).queryByLabelText('Без ОВЗ')).toBeNull()
    fireEvent.change(within(dialog).getByLabelText('Имя для табло (необязательно)'), {
      target: { value: 'Вера' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(server.bodies('PATCH /participants/*')).toEqual([{ display_name: 'Вера' }]))
  })

  test('создание ID и печать бейджей', async () => {
    server.routes.set('POST /participants/generate', () => json({ created: ['NT03', 'NT04'], total: 4 }))
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderAdmin(server)
    fireEvent.change(await screen.findByLabelText('Сколько ID создать'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Создать ID' }))
    expect(await screen.findByText('Создано: 2, всего 4')).toBeDefined()
    expect(server.bodies('POST /participants/generate')).toEqual([{ count: 4 }])

    fireEvent.click(screen.getByRole('button', { name: 'Печать бейджей' }))
    expect(open).toHaveBeenCalledWith(BADGES_URL, '_blank')
    open.mockRestore()
  })

  test('ошибка сервера показывается текстом', async () => {
    server.routes.set('POST /participants/generate', () => problem(403, 'forbidden'))
    renderAdmin(server)
    fireEvent.click(await screen.findByRole('button', { name: 'Создать ID' }))
    expect(await screen.findByText('Нет доступа')).toBeDefined()
  })
})

describe('станции', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  test('токен показывается один раз', async () => {
    const server = createFakeServer('admin')
    const stations: StationInfo[] = [
      { id: 1, name: 'Дартс-1', discipline: 'darts', online: true, last_heartbeat_at: '2027-01-01T09:00:00Z', last_state: 'idle', queue_length: 2 },
    ]
    server.routes.set('GET /stations', () => json(stations))
    server.routes.set('POST /stations', (body) => {
      const { name, discipline } = body as { name: string; discipline: string }
      stations.push({ id: 2, name, discipline: discipline as StationInfo['discipline'], online: false, last_heartbeat_at: null, last_state: null, queue_length: 0 })
      return json({ id: 2, name, discipline, token: 'SECRET-TOKEN-VALUE' }, 201)
    })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

    renderAdmin(server)
    await openTab('Станции')
    expect(await screen.findByText('Дартс-1')).toBeDefined()
    expect(screen.getByText('на связи')).toBeDefined()

    fireEvent.change(screen.getByLabelText('Название станции'), { target: { value: 'Футбол-1' } })
    fireEvent.change(screen.getByLabelText('Дисциплина'), { target: { value: 'football' } })
    fireEvent.click(screen.getByRole('button', { name: 'Создать станцию' }))

    const panel = await screen.findByRole('region', { name: 'Токен станции' })
    expect(within(panel).getByText('SECRET-TOKEN-VALUE')).toBeDefined()
    expect(within(panel).getByText(/Токен показан один раз/)).toBeDefined()
    expect(server.bodies('POST /stations')).toEqual([{ name: 'Футбол-1', discipline: 'football' }])

    fireEvent.click(within(panel).getByRole('button', { name: 'Скопировать токен' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('SECRET-TOKEN-VALUE'))
    expect(await within(panel).findByText('Скопировано')).toBeDefined()

    fireEvent.click(within(panel).getByRole('button', { name: 'Я сохранил токен' }))
    expect(screen.queryByText('SECRET-TOKEN-VALUE')).toBeNull()
    expect(screen.getByText('Футбол-1')).toBeDefined()
    expect(document.body.textContent).not.toContain('SECRET-TOKEN-VALUE')
  })

  test('новый токен выдаётся после подтверждения', async () => {
    const server = createFakeServer('admin')
    server.routes.set('GET /stations', () =>
      json([{ id: 7, name: 'Понг-1', discipline: 'pong', online: false, last_heartbeat_at: null, last_state: null, queue_length: 0 }]),
    )
    server.routes.set('POST /stations/*/rotate-token', () =>
      json({ id: 7, name: 'Понг-1', discipline: 'pong', token: 'NEW-TOKEN' }),
    )
    renderAdmin(server)
    await openTab('Станции')
    fireEvent.click(await screen.findByRole('button', { name: 'Новый токен Понг-1' }))
    expect(server.count('POST /stations/*/rotate-token')).toBe(0)
    const dialog = screen.getByRole('dialog', { name: 'Выдать новый токен?' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Выдать новый токен' }))
    expect(await screen.findByText('NEW-TOKEN')).toBeDefined()
    expect(screen.getByText('нет связи')).toBeDefined()
  })

  test('состояние станций обновляется раз в 5 секунд', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const server = createFakeServer('admin')
    let online = false
    server.routes.set('GET /stations', () =>
      json([{ id: 1, name: 'Дартс-1', discipline: 'darts', online, last_heartbeat_at: null, last_state: 'playing', queue_length: 3 }]),
    )
    renderAdmin(server)
    await openTab('Станции')
    expect(await screen.findByText('нет связи')).toBeDefined()
    const before = server.count('GET /stations')

    online = true
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(await screen.findByText('на связи')).toBeDefined()
    expect(server.count('GET /stations')).toBe(before + 1)
    expect(screen.getByText('игра')).toBeDefined()
  })
})

describe('жеребьёвка', () => {
  const options = [
    { m: 2, team_count: 2, reserve_general: 1, reserve_ovz: 0, reserve_total: 1 },
    { m: 3, team_count: 2, reserve_general: 0, reserve_ovz: 0, reserve_total: 0 },
  ]
  const protocol = {
    id: 1,
    created_at: '2027-01-01T09:00:00Z',
    seed: 77,
    m: 2,
    team_count: 2,
    teams: [
      { number: 1, name: 'Альфа', color: '#aa00bb', members: [{ code: 'NT01', number_in_team: 1 }] },
      { number: 2, name: 'Бета', color: '#00aa11', members: [{ code: 'NT02', number_in_team: 1 }] },
    ],
    duels: [{ order: 1, team_a: 1, team_b: 2, pairs: [{ k: 1, a: 'NT01', b: 'NT02' }] }],
    reserve_ovz: ['NT09'],
    reserve_general: ['NT10'],
  }

  test('запуск только после подтверждения, с выбранным m и зерном', async () => {
    const server = createFakeServer('admin')
    let done = false
    server.routes.set('GET /draw/options', () => json(options))
    server.routes.set('GET /draw', () => (done ? json(protocol) : problem(404, 'not_found')))
    server.routes.set('POST /draw', () => {
      done = true
      return json({ id: 1, seed: 77, m: 2, team_count: 2 })
    })
    renderAdmin(server)
    await openTab('Жеребьёвка')

    const run = await screen.findByRole('button', { name: 'Провести жеребьёвку' })
    expect((run as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(await screen.findByLabelText('m = 2'))
    fireEvent.change(screen.getByLabelText(/Зерно/), { target: { value: '77' } })
    fireEvent.click(run)

    const dialog = await screen.findByRole('dialog', { name: 'Провести жеребьёвку?' })
    expect(server.count('POST /draw')).toBe(0)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Да, провести' }))

    expect(await screen.findByLabelText('Протокол жеребьёвки')).toBeDefined()
    expect(server.bodies('POST /draw')).toEqual([{ m: 2, seed: 77 }])
  })

  test('отмена подтверждения ничего не запускает; без зерна оно не отправляется', async () => {
    const server = createFakeServer('admin')
    server.routes.set('GET /draw/options', () => json(options))
    server.routes.set('GET /draw', () => problem(404, 'not_found'))
    server.routes.set('POST /draw', () => json({ id: 1, seed: 5, m: 3, team_count: 2 }))
    renderAdmin(server)
    await openTab('Жеребьёвка')
    fireEvent.click(await screen.findByLabelText('m = 3'))
    fireEvent.click(screen.getByRole('button', { name: 'Провести жеребьёвку' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Отмена' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(server.count('POST /draw')).toBe(0)

    fireEvent.click(screen.getByRole('button', { name: 'Провести жеребьёвку' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Да, провести' }))
    await waitFor(() => expect(server.bodies('POST /draw')).toEqual([{ m: 3 }]))
  })

  test('зерно должно быть целым числом', async () => {
    const server = createFakeServer('admin')
    server.routes.set('GET /draw/options', () => json(options))
    server.routes.set('GET /draw', () => problem(404, 'not_found'))
    renderAdmin(server)
    await openTab('Жеребьёвка')
    fireEvent.click(await screen.findByLabelText('m = 2'))
    fireEvent.change(screen.getByLabelText(/Зерно/), { target: { value: 'abc' } })
    expect(screen.getByText('Зерно — целое число')).toBeDefined()
    expect((screen.getByRole('button', { name: 'Провести жеребьёвку' }) as HTMLButtonElement).disabled).toBe(true)
  })

  test('протокол: составы, пары, резерв по категориям и печать', async () => {
    const server = createFakeServer('admin')
    server.routes.set('GET /draw/options', () => json([]))
    server.routes.set('GET /draw', () => json(protocol))
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    renderAdmin(server)
    await openTab('Жеребьёвка')
    const article = await screen.findByLabelText('Протокол жеребьёвки')
    expect(within(article).getByText('77')).toBeDefined()
    expect(within(article).getByText('Дуэль 1: Альфа — Бета')).toBeDefined()
    expect(within(article).getByText('Пара 1: NT01 и NT02')).toBeDefined()
    expect(within(article).getByText('С ОВЗ: NT09')).toBeDefined()
    expect(within(article).getByText('Без ОВЗ: NT10')).toBeDefined()
    expect(screen.getByText(/Жеребьёвка уже проведена/)).toBeDefined()

    fireEvent.click(within(article).getByRole('button', { name: 'Печать протокола' }))
    expect(print).toHaveBeenCalledTimes(1)
    print.mockRestore()
  })
})

describe('названия и цвета команд', () => {
  const protocol = {
    id: 1,
    created_at: '2027-01-01T09:00:00Z',
    seed: 1,
    m: 1,
    team_count: 2,
    teams: [
      { number: 1, name: 'Красные', color: '#e6194b', members: [] },
      { number: 2, name: 'Синие', color: '#4363d8', members: [] },
    ],
    duels: [],
    reserve_ovz: [],
    reserve_general: [],
  }

  function setup() {
    const server = createFakeServer('admin')
    const teams = [
      { id: 11, number: 1, name: 'Красные', color: '#e6194b' },
      { id: 12, number: 2, name: 'Синие', color: '#4363d8' },
    ]
    server.routes.set('GET /draw/options', () => json([]))
    server.routes.set('GET /draw', () => json(protocol))
    server.routes.set('GET /teams', () => json({ teams, duels: [] }))
    server.routes.set('PATCH /teams/*', (body, url) => {
      const id = Number(url.pathname.split('/').at(-1))
      const team = teams.find((t) => t.id === id)
      Object.assign(team ?? {}, body)
      return json(team)
    })
    return server
  }

  test('админ переименовывает команду и выбирает цвет', async () => {
    const server = setup()
    renderAdmin(server)
    await openTab('Жеребьёвка')
    const name = await screen.findByLabelText('Название команды 1')
    const save = screen.getByRole('button', { name: 'Сохранить команду 1' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)

    fireEvent.change(name, { target: { value: '  Огонь  ' } })
    fireEvent.change(screen.getByLabelText('Цвет команды 1'), { target: { value: '#ff8800' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)

    await waitFor(() =>
      expect(server.bodies('PATCH /teams/*')).toEqual([{ name: 'Огонь', color: '#ff8800' }]),
    )
    expect(server.calls.find((c) => c.key === 'PATCH /teams/*')?.url.pathname).toBe('/api/v1/teams/11')
    await waitFor(() =>
      expect((screen.getByLabelText('Название команды 1') as HTMLInputElement).value).toBe('Огонь'),
    )
  })

  test('цвет выбирается нативным полем color', async () => {
    renderAdmin(setup())
    await openTab('Жеребьёвка')
    const color = (await screen.findByLabelText('Цвет команды 2')) as HTMLInputElement
    expect(color.type).toBe('color')
    expect(color.value).toBe('#4363d8')
  })

  test('пустое название нельзя сохранить, длина ограничена 24', async () => {
    const server = setup()
    renderAdmin(server)
    await openTab('Жеребьёвка')
    const name = (await screen.findByLabelText('Название команды 1')) as HTMLInputElement
    const save = screen.getByRole('button', { name: 'Сохранить команду 1' }) as HTMLButtonElement
    fireEvent.change(name, { target: { value: '   ' } })
    expect(save.disabled).toBe(true)
    fireEvent.change(name, { target: { value: 'Ф' } })
    expect(save.disabled).toBe(false)
    expect(name.maxLength).toBe(24)
    expect(server.count('PATCH /teams/*')).toBe(0)
  })

  test('ошибка сервера показывается, введённое остаётся', async () => {
    const server = setup()
    server.routes.set('PATCH /teams/*', () => problem(422, 'invalid_request'))
    renderAdmin(server)
    await openTab('Жеребьёвка')
    fireEvent.change(await screen.findByLabelText('Название команды 1'), { target: { value: 'Новая' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить команду 1' }))
    await waitFor(() => expect(server.count('PATCH /teams/*')).toBe(1))
    expect((screen.getByLabelText('Название команды 1') as HTMLInputElement).value).toBe('Новая')
  })
})

describe('дисциплины', () => {
  test('меняется только изменённое поле', async () => {
    const server = createFakeServer('admin')
    const rows = [
      { code: 'darts', game_duration_s: 120, physical_duration_s: 300, win_points: 10, max_section_points: 10 },
      { code: 'pong', game_duration_s: 180, physical_duration_s: 300, win_points: 10, max_section_points: 10 },
    ]
    server.routes.set('GET /disciplines', () => json(rows))
    server.routes.set('PATCH /disciplines/*', (body) => {
      Object.assign(rows[0] ?? {}, body)
      return json(rows[0])
    })
    renderAdmin(server)
    await openTab('Дисциплины')
    const group = await screen.findByRole('group', { name: 'Дартс' })
    const save = within(group).getByRole('button', { name: 'Сохранить Дартс' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)

    fireEvent.change(within(group).getByLabelText('Игра, с (Дартс)'), { target: { value: '150' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await within(group).findByText('Сохранено')
    expect(server.bodies('PATCH /disciplines/*')).toEqual([{ game_duration_s: 150 }])
    expect(server.calls.find((c) => c.key === 'PATCH /disciplines/*')?.url.pathname).toBe('/api/v1/disciplines/darts')
  })

  test('лимит очков за секцию меняется отдельным полем и не выходит за 1…1000', async () => {
    const server = createFakeServer('admin')
    const rows = [
      { code: 'darts', game_duration_s: 120, physical_duration_s: 300, win_points: 10, max_section_points: 10 },
    ]
    server.routes.set('GET /disciplines', () => json(rows))
    server.routes.set('PATCH /disciplines/*', (body) => {
      Object.assign(rows[0] ?? {}, body)
      return json(rows[0])
    })
    renderAdmin(server)
    await openTab('Дисциплины')
    const group = await screen.findByRole('group', { name: 'Дартс' })
    const limit = within(group).getByLabelText('Лимит секции, очк. (Дартс)') as HTMLInputElement
    const save = within(group).getByRole('button', { name: 'Сохранить Дартс' }) as HTMLButtonElement
    expect(limit.value).toBe('10')

    for (const bad of ['0', '1001', '2.5']) {
      fireEvent.change(limit, { target: { value: bad } })
      expect(save.disabled).toBe(true)
    }
    fireEvent.change(limit, { target: { value: '15' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await within(group).findByText('Сохранено')
    expect(server.bodies('PATCH /disciplines/*')).toEqual([{ max_section_points: 15 }])
  })

  test('значение вне пределов не отправляется', async () => {
    const server = createFakeServer('admin')
    server.routes.set('GET /disciplines', () =>
      json([{ code: 'darts', game_duration_s: 120, physical_duration_s: 300, win_points: 10, max_section_points: 10 }]),
    )
    renderAdmin(server)
    await openTab('Дисциплины')
    const group = await screen.findByRole('group', { name: 'Дартс' })
    fireEvent.change(within(group).getByLabelText('Игра, с (Дартс)'), { target: { value: '5' } })
    expect((within(group).getByRole('button', { name: 'Сохранить Дартс' }) as HTMLButtonElement).disabled).toBe(true)
    expect(within(group).getByText(/Проверьте значения/)).toBeDefined()
  })
})

describe('пользователи (суперпользователь)', () => {
  test('создание волонтёра, отключение и сброс пароля', async () => {
    const server = createFakeServer('superuser', 'root')
    const users: UserInfo[] = [{ id: 1, login: 'root', role: 'superuser', discipline: null, is_active: true }]
    server.routes.set('GET /users', () => json(users))
    server.routes.set('POST /users', (body) => {
      const b = body as { login: string; role: string; discipline?: string }
      users.push({
        id: 2,
        login: b.login,
        role: b.role as UserInfo['role'],
        discipline: (b.discipline as UserInfo['discipline']) ?? null,
        is_active: true,
      })
      return json(users[1], 201)
    })
    server.routes.set('PATCH /users/*', () => json(users[1]))
    server.routes.set('POST /users/*/revoke-sessions', () => new Response(null, { status: 204 }))
    renderAdmin(server)
    await openTab('Пользователи')

    fireEvent.change(await screen.findByLabelText('Логин'), { target: { value: 'dart1' } })
    fireEvent.change(screen.getByLabelText(/Пароль \(от 8/), { target: { value: 'longenough' } })
    fireEvent.change(screen.getByLabelText('Секция волонтёра'), { target: { value: 'pong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Создать аккаунт' }))
    expect(await screen.findByText('Аккаунт «dart1» создан')).toBeDefined()
    expect(server.bodies('POST /users')).toEqual([
      { login: 'dart1', password: 'longenough', role: 'volunteer', discipline: 'pong' },
    ])

    fireEvent.click(await screen.findByRole('button', { name: 'Отключить dart1' }))
    await waitFor(() => expect(server.bodies('PATCH /users/*')).toEqual([{ is_active: false }]))

    fireEvent.click(screen.getByRole('button', { name: 'Сбросить пароль dart1' }))
    const dialog = await screen.findByRole('dialog', { name: 'Новый пароль dart1' })
    fireEvent.change(within(dialog).getByLabelText('Новый пароль'), { target: { value: 'another-pass' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сменить пароль' }))
    await waitFor(() =>
      expect(server.bodies('PATCH /users/*')).toContainEqual({ password: 'another-pass' }),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Завершить сессии dart1' }))
    fireEvent.click(
      within(await screen.findByRole('dialog', { name: 'Завершить сессии?' })).getByRole('button', {
        name: 'Завершить сессии',
      }),
    )
    await waitFor(() => expect(server.count('POST /users/*/revoke-sessions')).toBe(1))
  })
})

describe('экспорт', () => {
  test('ссылка ведёт на XLSX', async () => {
    const server = createFakeServer('admin')
    server.routes.set('GET /participants', () => json([]))
    renderAdmin(server)
    await openTab('Экспорт XLSX')
    const link = await screen.findByRole('link', { name: 'Скачать XLSX' })
    expect(link.getAttribute('href')).toBe('/api/v1/export.xlsx')
  })
})
