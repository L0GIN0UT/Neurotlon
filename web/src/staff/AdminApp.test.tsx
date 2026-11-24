import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { createFakeServer, json, problem } from '../test/fakeServer.ts'
import type { FakeServer } from '../test/fakeServer.ts'
import { AdminApp } from './AdminApp.tsx'
import { BADGES_URL } from './api.ts'
import type { Participant, StationInfo, UserInfo } from './api.ts'

// Второе значение категории нужно только для проверки подсказки «разные категории» у пары.
const OTHER_CATEGORY = 'ovz' as const

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

  test('в списке участников категории нет', async () => {
    people[1] = person('NT02', { checked_in: true, category: OTHER_CATEGORY })
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

describe('команды', () => {
  const played = { session_id: 's', outcome: 'completed', reason: null, comment: null, status: 'confirmed', source: 'station', finished_at: '2027-01-01T10:00:00Z', version: 1, voided: false, discipline: 'darts', section: 'bci', points: 5, wins: null }
  let server: FakeServer
  let members: { code: string; display_name: string | null; number_in_team: number }[][]
  let results: unknown[]

  function payload() {
    return {
      teams: [
        { id: 11, number: 1, name: 'Красные', color: '#e6194b', members: members[0] },
        { id: 12, number: 2, name: 'Синие', color: '#4363d8', members: members[1] },
      ],
      duels: [],
    }
  }

  function member(code: string, n: number) {
    return { code, display_name: null, number_in_team: n }
  }

  beforeEach(() => {
    server = createFakeServer('admin')
    members = [[member('NT01', 1), member('NT02', 2)], [member('NT03', 1)]]
    results = []
    server.routes.set('GET /teams', () => json(payload()))
    server.routes.set('GET /participants', () =>
      json([
        person('NT01', { checked_in: true, category: 'general' }),
        person('NT02', { checked_in: true, category: 'general' }),
        person('NT03', { checked_in: true, category: OTHER_CATEGORY }),
        person('NT04', { checked_in: true, category: 'general', display_name: 'Дима' }),
        person('NT05'),
      ]),
    )
    server.routes.set('GET /results', () => json({ total: results.length, items: results }))
    server.routes.set('PUT /teams/assignment', (body) => {
      const lineup = (body as { teams: { members: string[] }[] }).teams
      members = lineup.map((t) => t.members.map((code, i) => member(code, i + 1)))
      return json(payload())
    })
  })

  const dataTransfer = () => ({ dataTransfer: { setData: () => undefined, effectAllowed: 'move' } })
  // Команды лежат в строках пар, поэтому «колонка команды» — это список пар.
  const column = async (name: string) =>
    name === 'Не распределены'
      ? within(await screen.findByRole('region', { name }))
      : within(await screen.findByRole('list', { name: 'Пары' }))
  const cardOf = (_area: string, code: string) =>
    screen.getByText(code).closest('[data-card]') as HTMLElement

  test('вкладки «Жеребьёвка» нет, есть три области и пары', async () => {
    renderAdmin(server)
    expect(await screen.findByRole('tab', { name: 'Команды' })).toBeDefined()
    expect(screen.queryByRole('tab', { name: 'Жеребьёвка' })).toBeNull()
    await openTab('Команды')

    const pool = await column('Не распределены')
    expect(pool.getByText('NT04')).toBeDefined()
    expect(pool.getByText('Дима')).toBeDefined()
    expect(pool.queryByText('NT05')).toBeNull()
    expect((await column('Команда 1')).getByText('NT02')).toBeDefined()
    expect((await column('Команда 2')).getByText('NT03')).toBeDefined()

    const rows = within(screen.getByRole('list', { name: 'Пары' })).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(within(rows[0] as HTMLElement).getByText('NT01')).toBeDefined()
    expect(within(rows[0] as HTMLElement).getByText('NT03')).toBeDefined()
    expect(within(rows[0] as HTMLElement).getByText('против')).toBeDefined()
    expect(within(rows[1] as HTMLElement).getByText('NT02')).toBeDefined()
    expect(within(rows[1] as HTMLElement).getByText('без пары')).toBeDefined()
    expect(document.body.textContent).not.toContain('Протокол жеребьёвки')
  })

  test('кнопки двигают игрока и отправляют полный состав', async () => {
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')

    fireEvent.click(within(cardOf('Не распределены', 'NT04')).getByRole('button', { name: 'В команду 2: NT04' }))
    await waitFor(() =>
      expect(server.bodies('PUT /teams/assignment')).toEqual([
        { teams: [{ number: 1, members: ['NT01', 'NT02'] }, { number: 2, members: ['NT03', 'NT04'] }] },
      ]),
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Вверх: NT02' }))
    await waitFor(() => expect(server.count('PUT /teams/assignment')).toBe(2))
    expect(server.bodies('PUT /teams/assignment')[1]).toEqual({
      teams: [{ number: 1, members: ['NT02', 'NT01'] }, { number: 2, members: ['NT03', 'NT04'] }],
    })

    fireEvent.click(await screen.findByRole('button', { name: 'В другую команду: NT01' }))
    await waitFor(() => expect(server.count('PUT /teams/assignment')).toBe(3))
    expect(server.bodies('PUT /teams/assignment')[2]).toEqual({
      teams: [{ number: 1, members: ['NT02'] }, { number: 2, members: ['NT03', 'NT04', 'NT01'] }],
    })

    fireEvent.click(await screen.findByRole('button', { name: 'Убрать из команды: NT04' }))
    await waitFor(() => expect(server.count('PUT /teams/assignment')).toBe(4))
    expect(server.bodies('PUT /teams/assignment')[3]).toEqual({
      teams: [{ number: 1, members: ['NT02'] }, { number: 2, members: ['NT03', 'NT01'] }],
    })
    expect((await column('Не распределены')).getByText('NT04')).toBeDefined()
  })

  test('перетаскивание переносит игрока на нужное место', async () => {
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')
    fireEvent.dragStart(cardOf('Не распределены', 'NT04'), dataTransfer())
    fireEvent.drop(cardOf('Команда 1', 'NT01'))
    await waitFor(() =>
      expect(server.bodies('PUT /teams/assignment')).toEqual([
        { teams: [{ number: 1, members: ['NT04', 'NT01', 'NT02'] }, { number: 2, members: ['NT03'] }] },
      ]),
    )
  })

  test('при ошибке 409 прежний вид возвращается и виден текст ошибки', async () => {
    server.routes.set('PUT /teams/assignment', () => problem(409, 'conflict'))
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')
    fireEvent.click(within(cardOf('Не распределены', 'NT04')).getByRole('button', { name: 'В команду 1: NT04' }))
    expect(await screen.findByText('Действие уже недоступно')).toBeDefined()
    expect((await column('Не распределены')).getByText('NT04')).toBeDefined()
    expect((await column('Команда 1')).queryByText('NT04')).toBeNull()
  })

  test('игрок с результатом закреплён, остальных можно двигать вокруг него', async () => {
    results = [
      { ...played, id: 1, participant_code: 'NT01' },
      { ...played, id: 2, participant_code: 'NT02', voided: true },
    ]
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')
    const locked = cardOf('Команда 1', 'NT01')
    expect(locked.getAttribute('draggable')).toBe('false')
    expect(within(locked).getByRole('img', { name: /место закреплено/ })).toBeDefined()
    expect(within(locked).queryByRole('button')).toBeNull()
    // NT02 с аннулированным результатом не закреплён, но вверх нельзя: NT01 на месте
    expect((screen.getByRole('button', { name: 'Вверх: NT02' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Убрать из команды: NT02' }) as HTMLButtonElement).disabled).toBe(false)

    fireEvent.dragStart(locked, dataTransfer())
    fireEvent.drop(cardOf('Команда 2', 'NT03'))
    expect(server.count('PUT /teams/assignment')).toBe(0)
  })

  test('нельзя оставить дыру перед закреплённым игроком', async () => {
    results = [{ ...played, id: 2, participant_code: 'NT02' }]
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')
    for (const label of ['Убрать из команды', 'В другую команду', 'Вниз']) {
      expect((screen.getByRole('button', { name: `${label}: NT01` }) as HTMLButtonElement).disabled).toBe(true)
    }
  })

  test('в паре из разных категорий есть подсказка', async () => {
    renderAdmin(server)
    await openTab('Команды')
    const pairs = within(await screen.findByRole('list', { name: 'Пары' }))
    const [first, second] = pairs.getAllByRole('listitem') as HTMLElement[]
    expect(within(first as HTMLElement).getByRole('img', { name: 'разные категории' })).toBeDefined()
    expect(within(second as HTMLElement).queryByRole('img', { name: 'разные категории' })).toBeNull()
    expect(document.body.textContent?.toLowerCase()).not.toContain('овз')
  })

  test('бросок на карточку занимает место цели: вниз и вверх внутри команды', async () => {
    members = [[member('NT01', 1), member('NT02', 2), member('NT04', 3)], [member('NT03', 1)]]
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')
    fireEvent.dragStart(cardOf('Команда 1', 'NT01'), dataTransfer())
    fireEvent.drop(cardOf('Команда 1', 'NT04'))
    await waitFor(() => expect(server.count('PUT /teams/assignment')).toBe(1))
    expect(server.bodies('PUT /teams/assignment')[0]).toEqual({
      teams: [{ number: 1, members: ['NT02', 'NT04', 'NT01'] }, { number: 2, members: ['NT03'] }],
    })

    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('NT01'))
    fireEvent.dragStart(cardOf('Команда 1', 'NT01'), dataTransfer())
    fireEvent.drop(cardOf('Команда 1', 'NT02'))
    await waitFor(() => expect(server.count('PUT /teams/assignment')).toBe(2))
    expect(server.bodies('PUT /teams/assignment')[1]).toEqual({
      teams: [{ number: 1, members: ['NT01', 'NT02', 'NT04'] }, { number: 2, members: ['NT03'] }],
    })
  })

  test('после хода фокус остаётся в карточке игрока, ход объявляется', async () => {
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')
    const down = screen.getByRole('button', { name: 'Вниз: NT01' })
    down.focus()
    fireEvent.click(down)
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('NT01: команда 1, место 2'))
    const active = document.activeElement as HTMLElement
    expect(active.closest('[data-card]')?.getAttribute('data-card')).toBe('NT01')
    expect(active.tagName).toBe('BUTTON')
  })

  test('пока идёт запрос, клики и перетаскивание игнорируются', async () => {
    const gate: { release?: () => void } = {}
    server.routes.set('PUT /teams/assignment', (body) => {
      const lineup = (body as { teams: { members: string[] }[] }).teams
      return new Promise<Response>((resolve) => {
        gate.release = () => {
          members = lineup.map((t) => t.members.map((code, i) => member(code, i + 1)))
          resolve(json(payload()))
        }
      })
    })
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')
    fireEvent.click(screen.getByRole('button', { name: 'Вниз: NT01' }))
    const other = await screen.findByRole('button', { name: 'В другую команду: NT02' })
    expect(other.getAttribute('aria-disabled')).toBe('true')
    expect((other as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(other)
    fireEvent.dragStart(cardOf('Команда 1', 'NT02'), dataTransfer())
    fireEvent.drop(cardOf('Команда 2', 'NT03'))
    expect(server.count('PUT /teams/assignment')).toBe(1)

    await act(async () => {
      gate.release?.()
    })
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'В другую команду: NT02' }).getAttribute('aria-disabled')).toBeNull(),
    )
    expect(server.count('PUT /teams/assignment')).toBe(1)
  })

  test('после 409 данные перечитываются: доска и замки обновляются', async () => {
    server.routes.set('PUT /teams/assignment', () => {
      results = [{ ...played, id: 1, participant_code: 'NT01' }]
      return problem(409, 'conflict')
    })
    renderAdmin(server)
    await openTab('Команды')
    await column('Команда 1')
    expect(within(cardOf('Команда 1', 'NT01')).queryByRole('img', { name: /закреплено/ })).toBeNull()
    const before: Record<string, number> = {}
    for (const key of ['GET /results', 'GET /participants', 'GET /teams']) before[key] = server.count(key)
    fireEvent.click(within(cardOf('Не распределены', 'NT04')).getByRole('button', { name: 'В команду 1: NT04' }))

    expect(await screen.findByText('Действие уже недоступно')).toBeDefined()
    await waitFor(() =>
      expect(within(cardOf('Команда 1', 'NT01')).getByRole('img', { name: /закреплено/ })).toBeDefined(),
    )
    for (const key of ['GET /results', 'GET /participants', 'GET /teams']) {
      expect(server.count(key)).toBe((before[key] ?? 0) + 1)
    }
    expect((await column('Не распределены')).getByText('NT04')).toBeDefined()
  })

  test('раз в 15 секунд вкладка сама подтягивает чужие изменения', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      renderAdmin(server)
      await openTab('Команды')
      await column('Команда 1')
      expect((await column('Не распределены')).queryByText('NT09')).toBeNull()
      server.routes.set('GET /participants', () =>
        json([person('NT01', { checked_in: true }), person('NT02', { checked_in: true }), person('NT03', { checked_in: true }), person('NT09', { checked_in: true })]),
      )
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000)
      })
      expect((await column('Не распределены')).getByText('NT09')).toBeDefined()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('названия и цвета команд', () => {
  function setup() {
    const server = createFakeServer('admin')
    const teams = [
      { id: 11, number: 1, name: 'Красные', color: '#e6194b' },
      { id: 12, number: 2, name: 'Синие', color: '#4363d8' },
    ]
    server.routes.set('GET /participants', () => json([]))
    server.routes.set('GET /results', () => json({ total: 0, items: [] }))
    server.routes.set('GET /teams', () =>
      json({ teams: teams.map((t) => ({ ...t, members: [] })), duels: [] }),
    )
    server.routes.set('PATCH /teams/*', (body, url) => {
      const id = Number(url.pathname.split('/').at(-1))
      const team = teams.find((t) => t.id === id)
      Object.assign(team ?? {}, body)
      return json(team)
    })
    return server
  }

  test('название и цвет сохраняются по потере фокуса', async () => {
    const server = setup()
    renderAdmin(server)
    await openTab('Команды')
    const name = await screen.findByLabelText('Название команды 1')
    fireEvent.blur(name)
    expect(server.count('PATCH /teams/*')).toBe(0)

    fireEvent.change(name, { target: { value: '  Огонь  ' } })
    fireEvent.change(screen.getByLabelText('Цвет команды 1'), { target: { value: '#ff8800' } })
    fireEvent.blur(name)

    await waitFor(() =>
      expect(server.bodies('PATCH /teams/*')).toEqual([{ name: 'Огонь', color: '#ff8800' }]),
    )
    expect(server.calls.find((c) => c.key === 'PATCH /teams/*')?.url.pathname).toBe('/api/v1/teams/11')
    await waitFor(() =>
      expect((screen.getByLabelText('Название команды 1') as HTMLInputElement).value).toBe('Огонь'),
    )
  })

  test('Enter сохраняет название', async () => {
    const server = setup()
    renderAdmin(server)
    await openTab('Команды')
    const name = await screen.findByLabelText('Название команды 2')
    fireEvent.change(name, { target: { value: 'Волны' } })
    fireEvent.keyDown(name, { key: 'Enter' })
    await waitFor(() =>
      expect(server.bodies('PATCH /teams/*')).toEqual([{ name: 'Волны', color: '#4363d8' }]),
    )
  })

  test('Enter и следующий blur шлют один запрос', async () => {
    const server = setup()
    renderAdmin(server)
    await openTab('Команды')
    const name = await screen.findByLabelText('Название команды 1')
    fireEvent.change(name, { target: { value: 'Огонь' } })
    fireEvent.keyDown(name, { key: 'Enter' })
    fireEvent.blur(name)
    await waitFor(() => expect(server.count('PATCH /teams/*')).toBe(1))
    await waitFor(() => expect((screen.getByLabelText('Название команды 1') as HTMLInputElement).value).toBe('Огонь'))
    fireEvent.blur(screen.getByLabelText('Название команды 1'))
    expect(server.count('PATCH /teams/*')).toBe(1)
  })

  test('пустое название по Enter показывает сообщение, запрос не уходит', async () => {
    const server = setup()
    renderAdmin(server)
    await openTab('Команды')
    const name = await screen.findByLabelText('Название команды 1')
    fireEvent.change(name, { target: { value: '   ' } })
    fireEvent.keyDown(name, { key: 'Enter' })
    expect(await screen.findByText(/от 1 до 24 символов/)).toBeDefined()
    expect(server.count('PATCH /teams/*')).toBe(0)
  })

  test('цвет выбирается нативным полем color', async () => {
    renderAdmin(setup())
    await openTab('Команды')
    const color = (await screen.findByLabelText('Цвет команды 2')) as HTMLInputElement
    expect(color.type).toBe('color')
    expect(color.value).toBe('#4363d8')
  })

  test('пустое название не сохраняется, длина ограничена 24', async () => {
    const server = setup()
    renderAdmin(server)
    await openTab('Команды')
    const name = (await screen.findByLabelText('Название команды 1')) as HTMLInputElement
    fireEvent.change(name, { target: { value: '   ' } })
    fireEvent.blur(name)
    expect(name.maxLength).toBe(24)
    expect(server.count('PATCH /teams/*')).toBe(0)
  })

  test('ошибка сервера показывается под шапкой, введённое остаётся', async () => {
    const server = setup()
    server.routes.set('PATCH /teams/*', () => problem(422, 'invalid_request'))
    renderAdmin(server)
    await openTab('Команды')
    const name = await screen.findByLabelText('Название команды 1')
    fireEvent.change(name, { target: { value: 'Новая' } })
    fireEvent.blur(name)
    await waitFor(() => expect(server.count('PATCH /teams/*')).toBe(1))
    expect(await screen.findByRole('alert')).toBeDefined()
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

    fireEvent.change(within(group).getByLabelText('Время игры, с (Дартс)'), { target: { value: '150' } })
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
    const limit = within(group).getByLabelText('Лимит очков за секцию (Дартс)') as HTMLInputElement
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
    fireEvent.change(within(group).getByLabelText('Время игры, с (Дартс)'), { target: { value: '5' } })
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
