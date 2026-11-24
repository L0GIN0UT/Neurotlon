import { useMemo, useState } from 'react'
import type { DragEvent, ReactNode } from 'react'
import { errorText } from '../../shared/messages.ts'
import type { Category, Participant, StaffApi, TeamInfo, TeamsPayload } from '../api.ts'
import { useAction, useLoader } from '../hooks.ts'
import { ErrorText } from '../ui.tsx'
import { TeamTitle } from './TeamsEditor.tsx'
import { assignmentBody, locate, moveTo, pairsOf, step } from './teamsLayout.ts'
import type { Area, Lineup, Lock, Locks } from './teamsLayout.ts'
import './TeamsTab.css'

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
  onMove: (code: string, target: Area) => void
  onStep: (code: string, direction: -1 | 1) => void
  onDragStart: (code: string) => void
  onDragEnd: () => void
  onDropAt: (area: Area, position?: number) => void
}

function Button({
  label,
  code,
  enabled,
  onClick,
  className,
  children,
}: {
  label: string
  code: string
  enabled: boolean
  onClick: () => void
  className: string
  children: ReactNode
}) {
  return (
    <button
      type="button"
      className={className}
      disabled={!enabled}
      title={label}
      aria-label={`${label}: ${code}`}
      onClick={onClick}
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
  const free = (next: Lineup | null) => !busy && next !== null
  const other: Area = area === 'team1' ? 'team2' : 'team1'

  return (
    <div
      className={`tm-card${locked ? ' locked' : ''}`}
      data-card={code}
      draggable={!locked && !busy}
      onDragStart={(e: DragEvent) => {
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
          <Button
            className="tm-mini"
            label="В команду 1"
            code={code}
            enabled={free(moveTo(lineup, locks, code, 'team1'))}
            onClick={() => handlers.onMove(code, 'team1')}
          >
            →1
          </Button>
          <Button
            className="tm-mini"
            label="В команду 2"
            code={code}
            enabled={free(moveTo(lineup, locks, code, 'team2'))}
            onClick={() => handlers.onMove(code, 'team2')}
          >
            →2
          </Button>
        </div>
      )}
      {!locked && area !== 'pool' && (
        <div className="tm-actions">
          <Button
            className="tm-icon"
            label="Вверх"
            code={code}
            enabled={free(step(lineup, locks, code, -1))}
            onClick={() => handlers.onStep(code, -1)}
          >
            <Icon>{ICONS.up}</Icon>
          </Button>
          <Button
            className="tm-icon"
            label="Вниз"
            code={code}
            enabled={free(step(lineup, locks, code, 1))}
            onClick={() => handlers.onStep(code, 1)}
          >
            <Icon>{ICONS.down}</Icon>
          </Button>
          <Button
            className="tm-icon"
            label="В другую команду"
            code={code}
            enabled={free(moveTo(lineup, locks, code, other))}
            onClick={() => handlers.onMove(code, other)}
          >
            <Icon>{ICONS.swap}</Icon>
          </Button>
          <Button
            className="tm-icon"
            label="Убрать из команды"
            code={code}
            enabled={free(moveTo(lineup, locks, code, 'pool'))}
            onClick={() => handlers.onMove(code, 'pool')}
          >
            <Icon>{ICONS.remove}</Icon>
          </Button>
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
    return (
      <PlayerCard code={code} area={area} index={index} board={board} busy={busy} handlers={handlers} />
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
  onSaved: () => void
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
      {team ? (
        <TeamTitle key={`${team.id}:${team.name}:${team.color}`} team={team} api={api} onSaved={onSaved} />
      ) : (
        <h3>Команда {number}</h3>
      )}
      <span className="tm-count" title="Игроков в команде">
        {count}
      </span>
    </div>
  )
}

function TeamsBoard({
  api,
  teams,
  start,
  people,
  locks,
  onSaved,
}: {
  api: StaffApi
  teams: TeamsPayload['teams']
  start: Lineup
  people: ReadonlyMap<string, Person>
  locks: Locks
  onSaved: () => void
}) {
  // committed — то, что сервер принял; pending — раскладка на время запроса.
  const [committed, setCommitted] = useState(start)
  const [pending, setPending] = useState<Lineup | null>(null)
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<Area | null>(null)
  const [poolOpen, setPoolOpen] = useState(
    () => typeof window.matchMedia !== 'function' || window.matchMedia('(min-width: 900px)').matches,
  )
  const action = useAction()
  const busy = action.busy
  const board: Board = { lineup: pending ?? committed, locks, people }

  async function apply(next: Lineup | null) {
    if (next === null || busy) return
    setPending(next)
    const saved = await action.run(() => api.assignTeams(assignmentBody(next)))
    if (saved !== undefined) {
      setCommitted(next)
      onSaved()
    }
    setPending(null)
  }

  function dropAt(area: Area, position?: number) {
    const code = dragging
    setDragging(null)
    setOver(null)
    if (code !== null) void apply(moveTo(board.lineup, locks, code, area, position))
  }

  const handlers: Handlers = {
    onMove: (code, target) => void apply(moveTo(board.lineup, locks, code, target)),
    onStep: (code, direction) => void apply(step(board.lineup, locks, code, direction)),
    onDragStart: setDragging,
    onDragEnd: () => {
      setDragging(null)
      setOver(null)
    },
    onDropAt: dropAt,
  }

  const rows = pairsOf(board.lineup)
  const teamOf = (n: number) => teams.find((t) => t.number === n)
  const pool = board.lineup.pool

  return (
    <>
      <ErrorText error={action.error === null ? null : errorText(action.error)} />
      <div className="tm-layout" aria-busy={busy}>
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
              onSaved={onSaved}
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
              onSaved={onSaved}
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

  const initial = useMemo(() => {
    if (!teams.data || !participants.data || !results.data) return null
    const lineup = lineupOf(teams.data, participants.data)
    const played = new Set(results.data.filter((r) => !r.voided).map((r) => r.participant_code))
    const people = new Map<string, Person>(
      participants.data.map((p) => [p.code, { name: p.display_name, category: p.category ?? null }]),
    )
    return { lineup, locks: locksOf(lineup, played), people }
  }, [teams.data, participants.data, results.data])

  return (
    <section className="stack">
      <ErrorText error={teams.error ?? participants.error ?? results.error} />
      {initial && teams.data && (
        <TeamsBoard
          api={api}
          teams={teams.data.teams}
          start={initial.lineup}
          people={initial.people}
          locks={initial.locks}
          onSaved={teams.reload}
        />
      )}
    </section>
  )
}
