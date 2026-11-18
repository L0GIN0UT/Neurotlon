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

  test('админ может открыть страницу судьи', async () => {
    const server = createFakeServer('admin')
    server.routes.set('GET /conflicts', () => json([]))
    renderJudge(server)
    expect(await screen.findByText('Конфликтов нет.')).toBeDefined()
  })
})

describe('конфликты', () => {
  test('судья оставляет один результат с причиной', async () => {
    const server = createFakeServer('judge', 'judy')
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

  function setup(role = 'judge') {
    const server = createFakeServer(role, 'judy')
    const row = stored()
    let open = [correction]
    server.routes.set('GET /conflicts', () => json([]))
    server.routes.set('GET /corrections', () => json(open))
    server.routes.set('GET /results', () => json([row]))
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
    fireEvent.change(within(form).getByLabelText('Очки'), { target: { value: '45' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    expect(await within(form).findByText('Укажите причину исправления')).toBeDefined()
    expect(server.count('PATCH /results/*')).toBe(0)

    fireEvent.change(within(form).getByLabelText('Причина исправления (в журнал)'), {
      target: { value: 'пересчёт бросков' },
    })
    fireEvent.click(within(form).getByRole('button', { name: 'Сохранить правку' }))
    await waitFor(() => expect(server.count('PATCH /results/*')).toBe(1))
    expect(server.bodies('PATCH /results/*')).toEqual([
      { points: 45, change_reason: 'пересчёт бросков' },
    ])
    expect(await within(card).findByText(/версия 2/)).toBeDefined()
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

  test('заблокированный результат судье не правится, админу правится', async () => {
    const judge = setup('judge')
    judge.server.routes.set('GET /results', () => json([stored({ status: 'locked' })]))
    const first = renderJudge(judge.server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const form = await screen.findByRole('form', { name: 'Правка 5' })
    expect(within(form).getByText(/правит админ/)).toBeDefined()
    expect(within(form).getByRole('button', { name: 'Сохранить правку' }).matches(':disabled')).toBe(true)
    first.unmount()

    const admin = setup('admin')
    admin.server.routes.set('GET /results', () => json([stored({ status: 'locked' })]))
    renderJudge(admin.server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const adminForm = await screen.findByRole('form', { name: 'Правка 5' })
    expect(within(adminForm).getByRole('button', { name: 'Сохранить правку' }).matches(':disabled')).toBe(false)
  })

  test('аннулированный результат не правится', async () => {
    const { server } = setup()
    server.routes.set('GET /results', () => json([stored({ voided: true })]))
    renderJudge(server)
    await openTab('Поиск и правка')
    fireEvent.click(await screen.findByRole('button', { name: 'Найти' }))
    const form = await screen.findByRole('form', { name: 'Правка 5' })
    expect(within(form).getByText(/аннулирован/)).toBeDefined()
  })
})

describe('фиксация итогов', () => {
  function setup() {
    const server = createFakeServer('judge', 'judy')
    server.routes.set('GET /conflicts', () => json([]))
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

  test('на странице судьи есть экспорт', async () => {
    renderJudge(setup())
    await openTab('Итоги')
    expect((await screen.findByRole('link', { name: 'Скачать XLSX' })).getAttribute('href')).toBe(
      '/api/v1/export.xlsx',
    )
  })
})
