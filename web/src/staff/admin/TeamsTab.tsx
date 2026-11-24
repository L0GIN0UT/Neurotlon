import { useMemo, useState } from 'react'
import type { DragEvent } from 'react'
import { errorText } from '../../shared/messages.ts'
import type { Category, Participant, StaffApi, TeamsPayload } from '../api.ts'
import { useAction, useLoader } from '../hooks.ts'
import { ErrorText } from '../ui.tsx'
import { TeamsEditor } from './TeamsEditor.tsx'
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

const AREAS: readonly Area[] = ['pool', 'team1', 'team2']

const AREA_TITLES: Record<Area, string> = {
  pool: 'Не распределены',
  team1: 'Команда 1',
  team2: 'Команда 2',
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

function LockIcon() {
  return (
    <svg
      className="tm-lock"
      viewBox="0 0 16 16"
      width="14"
      height="14"
      role="img"
      aria-label="Есть результат, место закреплено"
    >
      <rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor" />
      <path d="M5 7V5a3 3 0 0 1 6 0v2" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

interface Handlers {
  onMove: (code: string, target: Area) => void
  onStep: (code: string, direction: -1 | 1) => void
  onDragStart: (code: string) => void
  onDragEnd: () => void
  onDropAt: (area: Area, position?: number) => void
}

function CardButton({
  label,
  code,
  text,
  enabled,
  onClick,
}: {
  label: string
  code: string
  text: string
  enabled: boolean
  onClick: () => void
}) {
  return (
    <button type="button" disabled={!enabled} aria-label={`${label}: ${code}`} onClick={onClick}>
      {text}
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
    <li
      className={`tm-card${locked ? ' locked' : ''}`}
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
        {area !== 'pool' && <span className="tm-num">{index + 1}</span>}
        <strong>{code}</strong>
        {locked && <LockIcon />}
        {name && <span className="tm-name">{name}</span>}
      </div>
      {!locked && area === 'pool' && (
        <div className="tm-actions">
          <CardButton
            label="В команду 1"
            code={code}
            text="В команду 1"
            enabled={free(moveTo(lineup, locks, code, 'team1'))}
            onClick={() => handlers.onMove(code, 'team1')}
          />
          <CardButton
            label="В команду 2"
            code={code}
            text="В команду 2"
            enabled={free(moveTo(lineup, locks, code, 'team2'))}
            onClick={() => handlers.onMove(code, 'team2')}
          />
        </div>
      )}
      {!locked && area !== 'pool' && (
        <div className="tm-actions">
          <CardButton
            label="Вверх"
            code={code}
            text="Вверх"
            enabled={free(step(lineup, locks, code, -1))}
            onClick={() => handlers.onStep(code, -1)}
          />
          <CardButton
            label="Вниз"
            code={code}
            text="Вниз"
            enabled={free(step(lineup, locks, code, 1))}
            onClick={() => handlers.onStep(code, 1)}
          />
          <CardButton
            label="В другую команду"
            code={code}
            text="В другую"
            enabled={free(moveTo(lineup, locks, code, other))}
            onClick={() => handlers.onMove(code, other)}
          />
          <CardButton
            label="Убрать из команды"
            code={code}
            text="Убрать"
            enabled={free(moveTo(lineup, locks, code, 'pool'))}
            onClick={() => handlers.onMove(code, 'pool')}
          />
        </div>
      )}
    </li>
  )
}

function PairsList({ board }: { board: Board }) {
  const rows = pairsOf(board.lineup)
  return (
    <section className="tm-pairs card" aria-label="Пары">
      <h3>Пары</h3>
      {rows.length === 0 && <p className="muted">Команды пусты.</p>}
      <ol>
        {rows.map((row) => {
          const a = row.a === null ? undefined : board.people.get(row.a)
          const b = row.b === null ? undefined : board.people.get(row.b)
          const mixed = Boolean(a?.category && b?.category && a.category !== b.category)
          return (
            <li key={row.k} value={row.k}>
              {row.a !== null && row.b !== null ? (
                <span>
                  {row.a} против {row.b}
                </span>
              ) : (
                <span>
                  {row.a ?? row.b} <em>без пары</em>
                </span>
              )}
              {mixed && <span className="tm-warn">разные категории</span>}
            </li>
          )
        })}
      </ol>
    </section>
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

  return (
    <>
      <ErrorText error={action.error === null ? null : errorText(action.error)} />
      <div className="tm-board" aria-busy={busy}>
        {AREAS.map((area) => {
          const team = area === 'pool' ? undefined : teams.find((t) => t.number === (area === 'team1' ? 1 : 2))
          const list = board.lineup[area]
          return (
            <section
              key={area}
              className={`tm-column card${over === area ? ' over' : ''}`}
              aria-label={AREA_TITLES[area]}
              onDragOver={(e) => {
                e.preventDefault()
                setOver(area)
              }}
              onDragLeave={() => setOver((o) => (o === area ? null : o))}
              onDrop={(e) => {
                e.preventDefault()
                dropAt(area)
              }}
            >
              <h3>
                {team && <span className="swatch" style={{ background: team.color }} />}
                <span className="grow">
                  {AREA_TITLES[area]}
                  {team ? `: ${team.name}` : ''}
                </span>
                <span className="tm-count">{list.length}</span>
              </h3>
              <ul>
                {list.map((code, index) => (
                  <PlayerCard
                    key={code}
                    code={code}
                    area={area}
                    index={index}
                    board={board}
                    busy={busy}
                    handlers={handlers}
                  />
                ))}
              </ul>
              {list.length === 0 && <p className="muted">Пусто. Перетащите игрока сюда.</p>}
            </section>
          )
        })}
        <PairsList board={board} />
      </div>
    </>
  )
}

/** Ручная раскладка пришедших по двум командам; пары — по местам в командах. */
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
      <TeamsEditor api={api} onSaved={teams.reload} />
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
