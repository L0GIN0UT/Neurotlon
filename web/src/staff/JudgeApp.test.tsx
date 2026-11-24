import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { createFakeServer, json, problem } from '../test/fakeServer.ts'
import type { FakeServer } from '../test/fakeServer.ts'
import type { StoredResult } from './api.ts'
import { JudgeApp } from './JudgeApp.tsx'

function stored(extra: Partial<StoredResult> = {}): StoredResult {
  return {
    id: 5,
    session_id: 'sess-1',
    participant_code: 'NT01',
    discipline: 'darts',
    section: 'bci',
    outcome: 'completed',
    points: 40,
    wins: null,
    reason: null,
    comment: null,
    status: 'confirmed',
    source: 'station',
    finished_at: '2027-01-01T09:00:00Z',
    version: 1,
    voided: false,
    ...extra,
  }
}

function renderJudge(server: FakeServer) {
  return render(<JudgeApp fetchFn={server.fetchFn} />)
}

async function openTab(name: string) {
  fireEvent.click(await screen.findByRole('tab', { name }))
}

const conflict = {
  participant_code: 'NT03',
  discipline: 'football',
  section: 'physical',
  results: [
    { id: 11, points: 8, wins: null, outcome: 'completed', reason: null, source: 'volunteer', finished_at: '2027-01-01T09:00:00Z', created_at: '2027-01-01T09:00:00Z' },
    { id: 12, points: 9, wins: null, outcome: 'completed', reason: null, source: 'volunteer', finished_at: '2027-01-01T09:01:00Z', created_at: '2027-01-01T09:01:00Z' },
  ],
}

describe('роли', () => {
  test('волонтёру страница закрыта', async () => {
    const server = createFakeServer('volunteer', 'vol')
    renderJudge(server)
    expect(await screen.findByRole('heading', { name: 'Нет доступа' })).toBeDefined()
  })

  test('админ может открыть страницу результатов', async () => {
    const server = createFakeServer('admin')
    server.routes.set('GET /conflicts', () => json([]))
    renderJudge(server)
    expect(await screen.findByText('Конфликтов нет.')).toBeDefined()
  })
})

describe('конфликты', () => {
  test('админ оставляет один результат с причиной', async () => {
    const server = createFakeServer('admin', 'boss')
    let items = [conflict]
    server.routes.set('GET /conflicts', () => json(items))
    server.routes.set('POST /conflicts/resolve', () => {
      items = []
      return json({ voided: [11] })
    })
    renderJudge(server)
    const card = await screen.findByRole('article', { name: 'NT03 · Футбол · Физическая' })
    const submit = within(card).getByRole('button', { name: /Решить конфликт/ }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)

    fireEvent.click(within(card).getByLabelText(/Оставить №12/))
    expect(submit.disabled).toBe(true) // без причины нельзя
    fireEvent.change(within(card).getByLabelText('Причина решения'), { target: { value: 'второй точнее' } })
    fireEvent.click(submit)

    expect(await screen.findByText('Конфликтов нет.')).toBeDefined()
    expect(server.bodies('POST /conflicts/resolve')).toEqual([
      { keep_result_id: 12, reason: 'второй точнее' },
    ])
  })
})

describe('запросы на исправление и правка', () => {
  const correction = {
    id: 3,
    session_id: 'sess-1',
    participant_codes: ['NT01'],
    comment: 'ошиблись в очках',
    created_at: '2027-01-01T09:05:00Z',
    status: 'open',
    resolved_at: null,
  }

  function setup(role = 'admin') {
    const server = createFakeServer(role, 'judy')
    const row = stored()
    let open = [correction]
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /disciplines', () =>
      json(
        ['darts', 'football', 'pong'].map((code) => ({
          code,
          game_duration_s: 120,
          physical_duration_s: 300,
          win_points: 10,
          max_section_points: 10,
        })),
      ),
    )
    server.routes.set('GET /corrections', () => json(open))
    server.routes.set('GET /results', () => json({ total: 1, items: [row] }))
    server.routes.set('PATCH /results/*', (body) => {
      const patch = body as { points?: number }
      Object.assign(row, { points: patch.points ?? row.points, version: row.version + 1 })
      return json(row)
    })
    server.routes.set('POST /corrections/*/done', () => {
      open = []
      return json({ ...correction, status: 'done' })
    })
    return { server, row }
  }

  test('правка результата требует причину и уходит с change_reason', async () => {
    const { server } = setup()
    renderJudge(server)
    await openTab('Запросы на исправление')
    const card = await screen.findByRole('article', { name: 'Запрос 3' })
    expect(within(card).getByText(/ошиблись в очках/)).toBeDefined()
    fireEvent.click(within(card).getByRole('button', { name: 'Открыть результат 3' }))

    const form = await within(card).findByRole('form', { name: 'Правка 5' })
    expect(server.calls.find((c) => c.key === 'GET /results')?.url.search).toBe('?session_id=sess-1')
    fireEvent.change(within(form).getByLabelText('Очки'), { target: { value: '9' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    expect(await within(form).findByText('Укажите причину исправления')).toBeDefined()
    expect(server.count('PATCH /results/*')).toBe(0)

    fireEvent.change(within(form).getByLabelText('Причина исправления (в журнал)'), {
      target: { value: 'пересчёт бросков' },
    })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    await waitFor(() => expect(server.count('PATCH /results/*')).toBe(1))
    expect(server.bodies('PATCH /results/*')).toEqual([
      { points: 9, change_reason: 'пересчёт бросков' },
    ])
    expect(await within(card).findByText(/версия 2/)).toBeDefined()
  })

  test('очки выше лимита дисциплины не отправляются, ровно лимит проходит', async () => {
    const { server } = setup()
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const form = await screen.findByRole('form', { name: 'Правка 5' })
    await waitFor(() =>
      expect((within(form).getByLabelText('Очки') as HTMLInputElement).max).toBe('10'),
    )
    fireEvent.change(within(form).getByLabelText('Очки'), { target: { value: '11' } })
    fireEvent.change(within(form).getByLabelText('Причина исправления (в журнал)'), { target: { value: 'опечатка' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    expect(await within(form).findByText('Очки — целое число от 0 до 10')).toBeDefined()
    expect(server.count('PATCH /results/*')).toBe(0)

    fireEvent.change(within(form).getByLabelText('Очки'), { target: { value: '10' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    await waitFor(() => expect(server.count('PATCH /results/*')).toBe(1))
  })

  test('понг лимитом секции не ограничен', async () => {
    const { server } = setup()
    server.routes.set('GET /results', () =>
      json({ total: 1, items: [stored({ discipline: 'pong', points: 11, wins: 1 })] }),
    )
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const form = await screen.findByRole('form', { name: 'Правка 5' })
    await waitFor(() =>
      expect((within(form).getByLabelText('Очки') as HTMLInputElement).max).toBe('1000'),
    )
  })

  test('запрос отмечается выполненным', async () => {
    const { server } = setup()
    renderJudge(server)
    await openTab('Запросы на исправление')
    fireEvent.click(await screen.findByRole('button', { name: 'Отметить выполненным 3' }))
    expect(await screen.findByText('Открытых запросов нет.')).toBeDefined()
    expect(server.count('POST /corrections/*/done')).toBe(1)
  })

  test('поиск по участнику и дисциплине', async () => {
    const { server } = setup()
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.change(await screen.findByLabelText('ID участника'), { target: { value: 'NT01' } })
    fireEvent.change(screen.getByLabelText('Дисциплина'), { target: { value: 'darts' } })
    fireEvent.click(screen.getByRole('button', { name: 'Найти' }))
    expect(await screen.findByRole('form', { name: 'Правка 5' })).toBeDefined()
    expect(server.calls.find((c) => c.key === 'GET /results')?.url.search).toBe(
      '?participant=NT01&discipline=darts',
    )
  })

  test('смена исхода на «не пройдено» требует причину', async () => {
    const { server } = setup()
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const form = await screen.findByRole('form', { name: 'Правка 5' })
    fireEvent.change(within(form).getByLabelText('Исход'), { target: { value: 'not_completed' } })
    fireEvent.change(within(form).getByLabelText('Причина исправления (в журнал)'), { target: { value: 'отказ' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    expect(await within(form).findByText('Выберите причину «не пройдено»')).toBeDefined()
    fireEvent.change(within(form).getByLabelText('Причина «не пройдено»'), { target: { value: 'health' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    await waitFor(() =>
      expect(server.bodies('PATCH /results/*')).toEqual([
        { outcome: 'not_completed', reason: 'health', change_reason: 'отказ' },
      ]),
    )
  })

  test('сервер отклонил правку: ошибка видна, форма остаётся', async () => {
    const { server } = setup()
    server.routes.set('PATCH /results/*', () => problem(409, 'conflict'))
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const form = await screen.findByRole('form', { name: 'Правка 5' })
    fireEvent.change(within(form).getByLabelText('Очки'), { target: { value: '1' } })
    fireEvent.change(within(form).getByLabelText('Причина исправления (в журнал)'), { target: { value: 'x' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    expect(await within(form).findByText('Действие уже недоступно')).toBeDefined()
  })

  test('заблокированный результат правится', async () => {
    const admin = setup('admin')
    admin.server.routes.set('GET /results', () => json({ total: 1, items: [stored({ status: 'locked' })] }))
    renderJudge(admin.server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const adminForm = await screen.findByRole('form', { name: 'Правка 5' })
    expect(within(adminForm).getByRole('button', { name: 'Сохранить правку' }).matches(':disabled')).toBe(false)
  })

  test('аннулированный результат не правится', async () => {
    const { server } = setup()
    server.routes.set('GET /results', () => json({ total: 1, items: [stored({ voided: true })] }))
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const form = await screen.findByRole('form', { name: 'Правка 5' })
    expect(within(form).getByText(/аннулирован/)).toBeDefined()
  })
})

describe('фиксация итогов', () => {
  function setup() {
    const server = createFakeServer('admin', 'boss')
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /results', () => json({ total: 1, items: [stored()] }))
    server.routes.set('GET /corrections', () => json([]))
    server.routes.set('POST /results/lock', () => json({ locked: 12 }))
    return server
  }

  test('двойное подтверждение: запрос уходит только после второго', async () => {
    const server = setup()
    renderJudge(server)
    await openTab('Итоги')
    fireEvent.click(await screen.findByRole('button', { name: 'Зафиксировать итоги' }))

    const first = await screen.findByRole('dialog', { name: 'Зафиксировать итоги?' })
    fireEvent.click(within(first).getByRole('button', { name: 'Продолжить' }))
    expect(server.count('POST /results/lock')).toBe(0)

    const second = await screen.findByRole('dialog', { name: 'Точно зафиксировать?' })
    fireEvent.click(within(second).getByRole('button', { name: 'Да, зафиксировать' }))
    expect(await screen.findByText('Зафиксировано результатов: 12')).toBeDefined()
    expect(server.count('POST /results/lock')).toBe(1)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('отмена на любом шаге ничего не фиксирует', async () => {
    const server = setup()
    renderJudge(server)
    await openTab('Итоги')
    fireEvent.click(await screen.findByRole('button', { name: 'Зафиксировать итоги' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Отмена' }))
    expect(screen.queryByRole('dialog')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Зафиксировать итоги' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Продолжить' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Отмена' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(server.count('POST /results/lock')).toBe(0)
  })

  test('на странице результатов есть экспорт', async () => {
    renderJudge(setup())
    await openTab('Итоги')
    expect((await screen.findByRole('link', { name: 'Скачать XLSX' })).getAttribute('href')).toBe(
      '/api/v1/export.xlsx',
    )
  })
})

describe('панель итогов', () => {
  function summaryServer() {
    const server = createFakeServer('admin', 'boss')
    server.routes.set('GET /conflicts', () => json([conflict]))
    server.routes.set('GET /corrections', () =>
      json(
        [1, 2].map((id) => ({
          id,
          session_id: `sess-${id}`,
          participant_codes: ['NT01'],
          comment: 'проверьте',
          created_at: '2027-01-01T09:05:00Z',
          status: 'open',
          resolved_at: null,
        })),
      ),
    )
    server.routes.set('GET /results', () =>
      json({
        total: 5,
        items: [
          stored({ id: 1 }),
          stored({ id: 2 }),
          stored({ id: 3, status: 'locked' }),
          stored({ id: 4, status: 'entered' }),
          stored({ id: 5, voided: true }),
        ],
      }),
    )
    server.routes.set('POST /results/lock', () => json({ locked: 2 }))
    return server
  }

  function tile(label: string) {
    return screen.getByText(label).closest('div') as HTMLElement
  }

  test('плитки считают неаннулированные результаты по статусам', async () => {
    renderJudge(summaryServer())
    await openTab('Итоги')
    await waitFor(() => expect(within(tile('Всего результатов')).getByText('4')).toBeDefined())
    expect(within(tile('Подтверждено')).getByText('2')).toBeDefined()
    expect(within(tile('Зафиксировано')).getByText('1')).toBeDefined()
    expect(within(tile('Конфликтов')).getByText('1')).toBeDefined()
    expect(within(tile('Открытых запросов на исправление')).getByText('2')).toBeDefined()
  })

  test('чек-лист показывает конфликты и ведёт на вкладки', async () => {
    renderJudge(summaryServer())
    await openTab('Итоги')
    expect(await screen.findByText('Есть конфликты результатов: 1')).toBeDefined()
    expect(screen.getByText('Есть открытые запросы на исправление: 2')).toBeDefined()
    expect(screen.getByText('Есть что фиксировать (подтверждённых результатов: 2)')).toBeDefined()

    fireEvent.click(screen.getByRole('button', { name: 'Перейти к запросам' }))
    expect(await screen.findByRole('heading', { name: 'Запросы на исправление' })).toBeDefined()
    expect(screen.getByRole('tab', { name: 'Запросы на исправление' }).getAttribute('aria-selected')).toBe('true')

    await openTab('Итоги')
    fireEvent.click(await screen.findByRole('button', { name: 'Перейти к конфликтам' }))
    expect(await screen.findByRole('heading', { name: 'Конфликты результатов' })).toBeDefined()
  })

  test('при готовности все пункты выполнены, ссылок нет, в окне нет предупреждения', async () => {
    const server = createFakeServer('admin', 'boss')
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /corrections', () => json([]))
    server.routes.set('GET /results', () => json({ total: 1, items: [stored()] }))
    renderJudge(server)
    await openTab('Итоги')
    expect(await screen.findByText('Нет конфликтов результатов')).toBeDefined()
    expect(screen.getByText('Нет открытых запросов на исправление')).toBeDefined()
    expect(screen.queryByRole('button', { name: /Перейти/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Зафиксировать итоги' }))
    expect(within(await screen.findByRole('dialog')).queryByText('Не всё готово:')).toBeNull()
  })

  test('при невыполненных пунктах окно подтверждения предупреждает, но фиксация доступна', async () => {
    const server = summaryServer()
    renderJudge(server)
    await openTab('Итоги')
    await screen.findByText('Есть конфликты результатов: 1')
    fireEvent.click(screen.getByRole('button', { name: 'Зафиксировать итоги' }))
    const first = await screen.findByRole('dialog', { name: 'Зафиксировать итоги?' })
    expect(within(first).getByText('Неразрешённых конфликтов: 1')).toBeDefined()
    expect(within(first).getByText('Открытых запросов на исправление: 2')).toBeDefined()
    fireEvent.click(within(first).getByRole('button', { name: 'Продолжить' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Да, зафиксировать' }))
    expect(await screen.findByText('Зафиксировано результатов: 2')).toBeDefined()
    expect(server.count('POST /results/lock')).toBe(1)
  })
})

describe('панель итогов: данные недоступны или устарели', () => {
  test('ошибка загрузки: пометка у плиток и предупреждение в окне подтверждения', async () => {
    const server = createFakeServer('admin', 'boss')
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /corrections', () => json([]))
    server.routes.set('GET /results', () => problem(500, 'internal'))
    renderJudge(server)
    await openTab('Итоги')
    expect(await screen.findByText('Данные могли устареть')).toBeDefined()
    expect(screen.getByRole('alert')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Зафиксировать итоги' }))
    const dialog = await screen.findByRole('dialog', { name: 'Зафиксировать итоги?' })
    expect(within(dialog).getByText('Не удалось проверить готовность')).toBeDefined()
  })

  test('окно, открытое до ответа сервера, тоже предупреждает', async () => {
    const server = createFakeServer('admin', 'boss')
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /corrections', () => json([]))
    server.routes.set('GET /results', () => new Promise<Response>(() => {}))
    renderJudge(server)
    await openTab('Итоги')
    fireEvent.click(await screen.findByRole('button', { name: 'Зафиксировать итоги' }))
    const dialog = await screen.findByRole('dialog', { name: 'Зафиксировать итоги?' })
    expect(within(dialog).getByText('Не удалось проверить готовность')).toBeDefined()
  })

  test('открытие окна перезагружает счётчики', async () => {
    const server = createFakeServer('admin', 'boss')
    let conflicts: unknown[] = []
    server.routes.set('GET /conflicts', () => json(conflicts))
    server.routes.set('GET /corrections', () => json([]))
    server.routes.set('GET /results', () => json({ total: 1, items: [stored()] }))
    renderJudge(server)
    await openTab('Итоги')
    await screen.findByText('Нет конфликтов результатов')
    conflicts = [conflict]
    fireEvent.click(screen.getByRole('button', { name: 'Зафиксировать итоги' }))
    const dialog = await screen.findByRole('dialog', { name: 'Зафиксировать итоги?' })
    expect(await within(dialog).findByText('Неразрешённых конфликтов: 1')).toBeDefined()
  })

  test('пока данных нет, список плиток помечен занятым', async () => {
    const server = createFakeServer('admin', 'boss')
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /corrections', () => json([]))
    server.routes.set('GET /results', () => new Promise<Response>(() => {}))
    renderJudge(server)
    await openTab('Итоги')
    const list = await screen.findByLabelText('Сводка')
    expect(list.getAttribute('aria-busy')).toBe('true')
  })
})

describe('фиксация при блокировках', () => {
  function blockedServer(role: string) {
    const server = createFakeServer(role, 'who')
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /results', () => json({ total: 0, items: [] }))
    server.routes.set('GET /corrections', () => json([]))
    server.routes.set('POST /results/lock', (body) =>
      (body as { force?: boolean } | undefined)?.force
        ? json({ locked: 5 })
        : json(
            {
              type: 'about:blank',
              title: 'Conflict',
              status: 409,
              code: 'conflict',
              conflicts: 2,
              open_corrections: 1,
            },
            409,
          ),
    )
    return server
  }

  async function tryLock() {
    await openTab('Итоги')
    fireEvent.click(await screen.findByRole('button', { name: 'Зафиксировать итоги' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Продолжить' }))
    fireEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Да, зафиксировать' }),
    )
  }

  test('админ может зафиксировать принудительно', async () => {
    const server = blockedServer('admin')
    renderJudge(server)
    await tryLock()
    fireEvent.click(await screen.findByRole('button', { name: 'Всё равно зафиксировать' }))
    expect(await screen.findByText('Зафиксировано результатов: 5 (принудительно)')).toBeDefined()
    expect(server.bodies('POST /results/lock')).toEqual([undefined, { force: true }])
    expect(screen.queryByText('Неразрешённых конфликтов: 2')).toBeNull()
  })
})

describe('победитель в понге', () => {
  test('один выбор «Победитель»: назначение отправляет wins=1, текущего победителя снять нельзя', async () => {
    const server = createFakeServer('admin', 'boss')
    const rows = [
      stored({ id: 1, participant_code: 'NT03', discipline: 'pong', points: 11, wins: 1 }),
      stored({ id: 2, participant_code: 'NT04', discipline: 'pong', points: 7, wins: 0 }),
    ]
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /results', () => json({ total: 2, items: rows }))
    server.routes.set('PATCH /results/*', () => json(rows[1]))
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))

    const winner = await screen.findByRole('form', { name: 'Правка 1' })
    const winnerBox = within(winner).getByLabelText(/Победитель/) as HTMLInputElement
    expect(winnerBox.checked).toBe(true)
    expect(winnerBox.disabled).toBe(true)

    const loser = screen.getByRole('form', { name: 'Правка 2' })
    const box = within(loser).getByLabelText(/Победитель/) as HTMLInputElement
    expect(box.checked).toBe(false)
    fireEvent.click(box)
    fireEvent.change(within(loser).getByLabelText('Причина исправления (в журнал)'), {
      target: { value: 'админ пересмотрел' },
    })
    fireEvent.click(within(loser).getByRole('button', { name: 'Сохранить правку' }))
    await waitFor(() => expect(server.count('PATCH /results/*')).toBe(1))
    expect(server.bodies('PATCH /results/*')).toEqual([
      { wins: 1, change_reason: 'админ пересмотрел' },
    ])
  })
})

describe('длинный список результатов', () => {
  test('показывает, что найдено больше, чем выведено', async () => {
    const server = createFakeServer('admin', 'boss')
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /results', () => json({ total: 450, items: [stored()] }))
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    expect(await screen.findByText('Показано 1 из 450: уточните поиск.')).toBeDefined()
  })
})
