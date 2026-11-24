import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent, ReactNode, RefObject } from 'react'
import { errorText } from '../../shared/messages.ts'
import type { Category, Participant, StaffApi, TeamInfo, TeamsPayload } from '../api.ts'
import { useAction, useLoader } from '../hooks.ts'
import { ErrorText } from '../ui.tsx'
import { TeamTitle } from './TeamTitle.tsx'
import { assignmentBody, locate, moveTo, pairsOf, step } from './teamsLayout.ts'
import type { Area, Lineup, Lock, Locks } from './teamsLayout.ts'
import './TeamsTab.css'

/** Как часто вкладка перечитывает данные, если сейчас нет запроса и перетаскивания. */
const REFRESH_MS = 15_000

interface Person {
  name: string | null
  /** Только подсказка админу: пара из разных категорий помечается предупреждением. */
  category: Category | null
}

interface Board {
  lineup: Lineup
  locks: Locks
  people: ReadonlyMap<string, Person>
}

/** Что сделал человек: по нему возвращается фокус и объявляется результат. */
interface Moved {
  code: string
  /** Подпись кнопки, на которую вернуть фокус; у перетаскивания её нет. */
  label: string | null
}

function lineupOf(teams: TeamsPayload, participants: Participant[]): Lineup {
  const members = (number: number) =>
    [...(teams.teams.find((t) => t.number === number)?.members ?? [])]
      .sort((a, b) => a.number_in_team - b.number_in_team)
      .map((m) => m.code)
  const team1 = members(1)
  const team2 = members(2)
  const placed = new Set([...team1, ...team2])
  const pool = participants
    .filter((p) => p.checked_in && !placed.has(p.code))
    .map((p) => p.code)
    .sort()
  return { pool, team1, team2 }
}

function locksOf(lineup: Lineup, played: ReadonlySet<string>): Locks {
  const locks = new Map<string, Lock>()
  for (const code of played) {
    const at = locate(lineup, code)
    if (at !== null) locks.set(code, at)
  }
  return locks
}

function announcement(lineup: Lineup, code: string): string {
  const at = locate(lineup, code)
  if (at === null || at.area === 'pool') return `${code}: не распределён`
  return `${code}: команда ${at.area === 'team1' ? 1 : 2}, место ${at.index + 1}`
}

function Icon({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {children}
    </svg>
  )
}

const ICONS = {
  up: <path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" />,
  down: <path d="M8 3v10M3.5 8.5 8 13l4.5-4.5" />,
  swap: <path d="M2 5.5h11M10 2.5l3 3-3 3M14 10.5H3M6 7.5l-3 3 3 3" />,
  remove: <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />,
}

interface Handlers {
  onMove: (code: string, target: Area, label: string) => void
  onStep: (code: string, direction: -1 | 1, label: string) => void
  onDragStart: (code: string) => void
  onDragEnd: () => void
  onDropAt: (area: Area, position?: number) => void
}

/** Во время запроса кнопка не отключается (иначе пропадёт фокус), а только помечается и не реагирует. */
function CardButton({
  label,
  code,
  possible,
  busy,
  onClick,
  className,
  children,
}: {
  label: string
  code: string
  possible: boolean
  busy: boolean
  onClick: () => void
  className: string
  children: ReactNode
}) {
  return (
    <button
      type="button"
      className={className}
      disabled={!possible}
      aria-disabled={busy || undefined}
      title={label}
      aria-label={`${label}: ${code}`}
      onClick={() => {
        if (!busy) onClick()
      }}
    >
      {children}
    </button>
  )
}

function PlayerCard({
  code,
  area,
  index,
  board,
  busy,
  handlers,
}: {
  code: string
  area: Area
  index: number
  board: Board
  busy: boolean
  handlers: Handlers
}) {
  const { lineup, locks } = board
  const locked = locks.has(code)
  const name = board.people.get(code)?.name
  const other: Area = area === 'team1' ? 'team2' : 'team1'
  const to = (target: Area) => moveTo(lineup, locks, code, target) !== null

  return (
    <div
      className={`tm-card${locked ? ' locked' : ''}`}
      data-card={code}
      tabIndex={-1}
      draggable={!locked}
      onDragStart={(e: DragEvent) => {
        if (busy) {
          e.preventDefault()
          return
        }
        e.dataTransfer.setData('text/plain', code)
        e.dataTransfer.effectAllowed = 'move'
        handlers.onDragStart(code)
      }}
      onDragEnd={handlers.onDragEnd}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault()
        e.stopPropagation()
        handlers.onDropAt(area, index)
      }}
    >
      <div className="tm-card-head">
        <strong>{code}</strong>
        {locked && (
          <Icon label="Есть результат, место закреплено">
            <rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor" />
            <path d="M5 7V5a3 3 0 0 1 6 0v2" />
          </Icon>
        )}
        {name && <span className="tm-name">{name}</span>}
      </div>
      {!locked && area === 'pool' && (
        <div className="tm-actions always">
          <CardButton
            className="tm-mini"
            label="В команду 1"
            code={code}
            busy={busy}
            possible={to('team1')}
            onClick={() => handlers.onMove(code, 'team1', 'В команду 1')}
          >
            →1
          </CardButton>
          <CardButton
            className="tm-mini"
            label="В команду 2"
            code={code}
            busy={busy}
            possible={to('team2')}
            onClick={() => handlers.onMove(code, 'team2', 'В команду 2')}
          >
            →2
          </CardButton>
        </div>
      )}
      {!locked && area !== 'pool' && (
        <div className="tm-actions">
          <CardButton
            className="tm-icon"
            label="Вверх"
            code={code}
            busy={busy}
            possible={step(lineup, locks, code, -1) !== null}
            onClick={() => handlers.onStep(code, -1, 'Вверх')}
          >
            <Icon>{ICONS.up}</Icon>
          </CardButton>
          <CardButton
            className="tm-icon"
            label="Вниз"
            code={code}
            busy={busy}
            possible={step(lineup, locks, code, 1) !== null}
            onClick={() => handlers.onStep(code, 1, 'Вниз')}
          >
            <Icon>{ICONS.down}</Icon>
          </CardButton>
          <CardButton
            className="tm-icon"
            label="В другую команду"
            code={code}
            busy={busy}
            possible={to(other)}
            onClick={() => handlers.onMove(code, other, 'В другую команду')}
          >
            <Icon>{ICONS.swap}</Icon>
          </CardButton>
          <CardButton
            className="tm-icon"
            label="Убрать из команды"
            code={code}
            busy={busy}
            possible={to('pool')}
            onClick={() => handlers.onMove(code, 'pool', 'Убрать из команды')}
          >
            <Icon>{ICONS.remove}</Icon>
          </CardButton>
        </div>
      )}
    </div>
  )
}

function Cell({
  code,
  area,
  index,
  board,
  busy,
  handlers,
}: {
  code: string | null
  area: 'team1' | 'team2'
  index: number
  board: Board
  busy: boolean
  handlers: Handlers
}) {
  if (code !== null) {
    // key по коду: карточка другого игрока в той же строке не наследует чужой фокус.
    return (
      <PlayerCard
        key={code}
        code={code}
        area={area}
        index={index}
        board={board}
        busy={busy}
        handlers={handlers}
      />
    )
  }
  return (
    <div
      className="tm-empty"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault()
        e.stopPropagation()
        handlers.onDropAt(area)
      }}
    >
      без пары
    </div>
  )
}

function TeamHead({
  area,
  team,
  count,
  api,
  onSaved,
  handlers,
  over,
  setOver,
}: {
  area: 'team1' | 'team2'
  team: TeamInfo | undefined
  count: number
  api: StaffApi
  onSaved: (team: TeamInfo) => void
  handlers: Handlers
  over: Area | null
  setOver: (area: Area | null) => void
}) {
  const number = area === 'team1' ? 1 : 2
  return (
    <div
      className={`tm-head${over === area ? ' over' : ''}`}
      onDragOver={(e) => {
        e.preventDefault()
        setOver(area)
      }}
      onDragLeave={() => setOver(null)}
      onDrop={(e) => {
        e.preventDefault()
        handlers.onDropAt(area)
      }}
    >
      {team ? <TeamTitle team={team} api={api} onSaved={onSaved} /> : <h3>Команда {number}</h3>}
      <span className="tm-count" title="Игроков в команде">
        {count}
      </span>
    </div>
  )
}

function TeamsBoard({
  api,
  teams,
  board: server,
  idleRef,
  onAssigned,
  onFailed,
  onTeamSaved,
}: {
  api: StaffApi
  teams: TeamsPayload['teams']
  board: Board
  /** Ложь, пока идёт запрос или перетаскивание: тогда фоновое обновление пропускается. */
  idleRef: RefObject<boolean>
  onAssigned: (saved: TeamsPayload) => void
  onFailed: () => void
  onTeamSaved: (team: TeamInfo) => void
}) {
  const [pending, setPending] = useState<Lineup | null>(null)
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<Area | null>(null)
  const [announce, setAnnounce] = useState('')
  const [poolOpen, setPoolOpen] = useState(
    () => typeof window.matchMedia !== 'function' || window.matchMedia('(min-width: 900px)').matches,
  )
  const action = useAction()
  const inflight = useRef(false)
  const focus = useRef<Moved | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const busy = action.busy
  const board: Board = { ...server, lineup: pending ?? server.lineup }
  const { locks } = board

  // После хода возвращаем фокус на ту же кнопку на новом месте карточки (или на ближайшую рабочую).
  useEffect(() => {
    const moved = focus.current
    if (moved === null || root.current === null) return
    const card = root.current.querySelector<HTMLElement>(`[data-card="${moved.code}"]`)
    if (card === null) return
    focus.current = null
    if (moved.label === null) return
    const buttons = [...card.querySelectorAll<HTMLButtonElement>('button')]
    const same = buttons.find((b) => b.getAttribute('aria-label') === `${moved.label}: ${moved.code}`)
    const target = same && !same.disabled ? same : buttons.find((b) => !b.disabled)
    ;(target ?? card).focus()
  }, [pending, server.lineup])

  async function apply(next: Lineup | null, moved: Moved) {
    if (next === null || inflight.current) return
    inflight.current = true
    idleRef.current = false
    focus.current = moved
    setPending(next)
    const saved = await action.run(() => api.assignTeams(assignmentBody(next)))
    inflight.current = false
    idleRef.current = dragging === null
    if (saved === undefined) {
      // Данные могли устареть (чужие правки, новый результат): перечитываем всё.
      focus.current = moved
      onFailed()
    } else {
      setAnnounce(announcement(next, moved.code))
      onAssigned(saved)
    }
    setPending(null)
  }

  function endDrag() {
    setDragging(null)
    setOver(null)
    idleRef.current = !inflight.current
  }

  function dropAt(area: Area, position?: number) {
    const code = dragging
    endDrag()
    if (code !== null) {
      void apply(moveTo(board.lineup, locks, code, area, position), { code, label: null })
    }
  }

  const handlers: Handlers = {
    onMove: (code, target, label) =>
      void apply(moveTo(board.lineup, locks, code, target), { code, label }),
    onStep: (code, direction, label) =>
      void apply(step(board.lineup, locks, code, direction), { code, label }),
    onDragStart: (code) => {
      if (inflight.current) return
      setDragging(code)
      idleRef.current = false
    },
    onDragEnd: endDrag,
    onDropAt: dropAt,
  }

  const rows = pairsOf(board.lineup)
  const teamOf = (n: number) => teams.find((t) => t.number === n)
  const pool = board.lineup.pool

  return (
    <>
      <ErrorText error={action.error === null ? null : errorText(action.error)} />
      <p className="tm-sr" role="status" aria-live="polite">
        {announce}
      </p>
      <div className="tm-layout" aria-busy={busy} ref={root}>
        <section
          className={`tm-pool card${over === 'pool' ? ' over' : ''}`}
          aria-label="Не распределены"
          onDragOver={(e) => {
            e.preventDefault()
            setOver('pool')
          }}
          onDragLeave={() => setOver(null)}
          onDrop={(e) => {
            e.preventDefault()
            dropAt('pool')
          }}
        >
          <details open={poolOpen} onToggle={(e) => setPoolOpen(e.currentTarget.open)}>
            <summary>
              Не распределены <span className="tm-count">{pool.length}</span>
            </summary>
            <div className="tm-pool-list">
              {pool.map((code, index) => (
                <PlayerCard
                  key={code}
                  code={code}
                  area="pool"
                  index={index}
                  board={board}
                  busy={busy}
                  handlers={handlers}
                />
              ))}
              {pool.length === 0 && <p className="muted">Пусто</p>}
            </div>
          </details>
        </section>

        <section className="tm-teams card" aria-label="Команды">
          <div className="tm-row tm-heads">
            <TeamHead
              area="team1"
              team={teamOf(1)}
              count={board.lineup.team1.length}
              api={api}
              onSaved={onTeamSaved}
              handlers={handlers}
              over={over}
              setOver={setOver}
            />
            <span />
            <TeamHead
              area="team2"
              team={teamOf(2)}
              count={board.lineup.team2.length}
              api={api}
              onSaved={onTeamSaved}
              handlers={handlers}
              over={over}
              setOver={setOver}
            />
          </div>
          <ol className="tm-rows" aria-label="Пары">
            {rows.map((row, i) => {
              const a = row.a === null ? undefined : board.people.get(row.a)
              const b = row.b === null ? undefined : board.people.get(row.b)
              const mixed = Boolean(a?.category && b?.category && a.category !== b.category)
              return (
                <li key={row.k} className="tm-row" value={row.k}>
                  <Cell code={row.a} area="team1" index={i} board={board} busy={busy} handlers={handlers} />
                  <span className="tm-vs">
                    против
                    {mixed && (
                      <span className="tm-warn">
                        <Icon label="разные категории">
                          <path d="M8 2 14.5 13.5h-13z" />
                          <path d="M8 6.5v3.2M8 11.6v.1" />
                        </Icon>
                      </span>
                    )}
                  </span>
                  <Cell code={row.b} area="team2" index={i} board={board} busy={busy} handlers={handlers} />
                </li>
              )
            })}
          </ol>
          {rows.length === 0 && <p className="muted">Перетащите игроков в команды или нажмите →1 и →2.</p>}
        </section>
      </div>
    </>
  )
}

/** Ручная раскладка пришедших по двум командам; пары — строки напротив друг друга. */
export function TeamsTab({ api }: { api: StaffApi }) {
  const teams = useLoader(() => api.teams())
  const participants = useLoader(() => api.participants())
  const results = useLoader(() => api.allResults())
  // Ответ сервера на сохранение действует, пока вкладка не получила свежий список команд.
  const [override, setOverride] = useState<{ base: TeamsPayload | undefined; teams: TeamsPayload } | null>(null)
  const idleRef = useRef(true)

  const reloadTeams = teams.reload
  const reloadParticipants = participants.reload
  const reloadResults = results.reload
  const reloadAll = useCallback(() => {
    reloadTeams()
    reloadParticipants()
    reloadResults()
  }, [reloadTeams, reloadParticipants, reloadResults])

  useEffect(() => {
    const timer = setInterval(() => {
      if (idleRef.current) reloadAll()
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [reloadAll])

  const current = override !== null && override.base === teams.data ? override.teams : teams.data

  const board = useMemo(() => {
    if (!current || !participants.data || !results.data) return null
    const lineup = lineupOf(current, participants.data)
    const played = new Set(results.data.filter((r) => !r.voided).map((r) => r.participant_code))
    const people = new Map<string, Person>(
      participants.data.map((p) => [p.code, { name: p.display_name, category: p.category ?? null }]),
    )
    return { lineup, locks: locksOf(lineup, played), people }
  }, [current, participants.data, results.data])

  return (
    <section className="stack">
      <ErrorText error={teams.error ?? participants.error ?? results.error} />
      {board && current && (
        <TeamsBoard
          api={api}
          teams={current.teams}
          board={board}
          idleRef={idleRef}
          onAssigned={(saved) => setOverride({ base: teams.data, teams: saved })}
          onFailed={reloadAll}
          onTeamSaved={(saved) =>
            setOverride({
              base: teams.data,
              teams: { teams: current.teams.map((t) => (t.id === saved.id ? { ...t, ...saved } : t)) },
            })
          }
        />
      )}
    </section>
  )
}
