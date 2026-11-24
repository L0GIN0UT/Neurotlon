import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode, RefObject } from 'react'
import { LayoutGroup, MotionConfig, motion } from 'motion/react'
import { errorText } from '../../shared/messages.ts'
import type { Category, Participant, StaffApi, TeamInfo, TeamsPayload } from '../api.ts'
import { useAction, useLoader } from '../hooks.ts'
import { ErrorText } from '../ui.tsx'
import { TeamTitle } from './TeamTitle.tsx'
import { TEAM_AREAS, assignmentBody, dropPreview, locate, moveTo, pairsOf, step } from './teamsLayout.ts'
import type { Area, Lineup, Lock, Locks } from './teamsLayout.ts'
import { useCardDrag } from './useCardDrag.ts'
import type { DropTarget } from './useCardDrag.ts'
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
  /** Во время перетаскивания: чья карточка «призрак» на будущем месте и с какой стороны линия вставки. */
  drag?: { code: string; line: 'before' | 'after' } | null
  /** Область, над которой сейчас указатель: колонка подсвечивается. */
  hot?: Area | null
}

/** Что сделал человек: по нему возвращается фокус и объявляется результат. */
interface Moved {
  code: string
  /** Подпись кнопки, на которую вернуть фокус; у перетаскивания её нет. */
  label: string | null
  /** Ход закончился неудачей: фокус возвращается без ожидания показа нового состава. */
  settled?: boolean
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

const LOCKED_TITLE = 'У игрока есть результат, место закреплено'

/** Ручка «гриф»: шесть точек. Тянуть можно за всю карточку, ручка только подсказывает. */
function Grip() {
  return (
    // data-grip: пальцем карточку берут только за ручку, остальная карточка прокручивает страницу
    <span className="tm-grip" data-grip="">
      <svg viewBox="0 0 10 16" width="10" height="16" fill="currentColor" aria-hidden="true">
        {[3, 8, 13].flatMap((y) => [2.5, 7.5].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.3" />))}
      </svg>
    </span>
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
  onGrab: (event: ReactPointerEvent<HTMLElement>, code: string) => void
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
  const ghost = board.drag?.code === code ? board.drag.line : null

  return (
    <motion.div
      layout="position"
      layoutId={`tm-${code}`}
      transition={{ duration: 0.16, ease: 'easeOut' }}
      className={`tm-card${locked ? ' locked' : ''}${ghost ? ` ghost line-${ghost}` : ''}`}
      data-card={code}
      data-area={area}
      data-index={index}
      title={locked ? LOCKED_TITLE : undefined}
      tabIndex={-1}
      onPointerDown={(e) => {
        if (!locked && !busy) handlers.onGrab(e, code)
      }}
    >
      {!locked && <Grip />}
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
    </motion.div>
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
    <div className={`tm-empty${board.hot === area ? ' hot' : ''}`}>без пары</div>
  )
}

function TeamHead({
  area,
  team,
  count,
  api,
  onSaved,
  over,
}: {
  area: 'team1' | 'team2'
  team: TeamInfo | undefined
  count: number
  api: StaffApi
  onSaved: (team: TeamInfo) => void
  over: boolean
}) {
  const number = area === 'team1' ? 1 : 2
  return (
    <div className={`tm-head${over ? ' over' : ''}`}>
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
  const [announce, setAnnounce] = useState('')
  const [poolOpen, setPoolOpen] = useState(
    () => typeof window.matchMedia !== 'function' || window.matchMedia('(min-width: 900px)').matches,
  )
  const action = useAction()
  const inflight = useRef(false)
  const focus = useRef<Moved | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const busy = action.busy
  const base: Lineup = pending ?? server.lineup
  const { locks } = server

  const { drag, begin } = useCardDrag(root, {
    canStart: (code) => !inflight.current && !locks.has(code),
    onActiveChange: (active) => {
      idleRef.current = !active && !inflight.current
    },
    onDrop: (code, target) => dropAt(code, target),
  })
  // Раскладка «как будет после отпускания»: карточки уже сдвинуты, пары видны сразу.
  const target = drag?.target ?? null
  const preview =
    drag !== null && target !== null ? dropPreview(base, locks, drag.code, target.area, target.slot) : null
  const refused = drag !== null && target !== null && preview === null
  const shown = preview ?? base
  const dragArea = drag !== null && preview !== null ? locate(preview, drag.code) : null
  const board: Board = {
    ...server,
    lineup: shown,
    drag:
      drag !== null && dragArea !== null
        ? {
            code: drag.code,
            line:
              dragArea.area !== 'pool' && dragArea.index > 0 && dragArea.index === shown[dragArea.area].length - 1
                ? 'after'
                : 'before',
          }
        : null,
    hot: target?.area ?? null,
  }

  // После хода возвращаем фокус на ту же кнопку на новом месте карточки (или на ближайшую рабочую).
  useEffect(() => {
    const moved = focus.current
    if (moved === null || root.current === null) return
    // Эффект от более раннего обновления данных мог запоздать и сработать до показа хода:
    // ждём коммита с новым составом (pending), иначе фокус «съестся» до перемещения карточки.
    if (pending === null && !moved.settled) return
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
    idleRef.current = true
    if (saved === undefined) {
      // Данные могли устареть (чужие правки, новый результат): перечитываем всё.
      focus.current = { ...moved, settled: true }
      onFailed()
    } else {
      setAnnounce(announcement(next, moved.code))
      onAssigned(saved)
    }
    setPending(null)
  }

  function dropAt(code: string, at: DropTarget) {
    void apply(moveTo(base, locks, code, at.area, at.slot), { code, label: null })
  }

  const handlers: Handlers = {
    onMove: (code, area, label) => void apply(moveTo(base, locks, code, area), { code, label }),
    onStep: (code, direction, label) => void apply(step(base, locks, code, direction), { code, label }),
    onGrab: begin,
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
      <MotionConfig reducedMotion="user">
      <LayoutGroup id="teams">
        <div className={`tm-layout${drag ? ' dragging' : ''}`} aria-busy={busy} ref={root}>
          <section
            className={`tm-pool card${board.hot === 'pool' ? (refused ? ' over refused' : ' over') : ''}`}
            aria-label="Не распределены"
            data-zone="pool"
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
            <div className="tm-grid">
              {TEAM_AREAS.map((area) => (
                <i
                  key={area}
                  className={`tm-colbox ${area}${board.hot === area ? (refused ? ' on refused' : ' on') : ''}`}
                  data-zone={area}
                  aria-hidden="true"
                />
              ))}
              <div className="tm-row tm-heads">
                <TeamHead
                  area="team1"
                  team={teamOf(1)}
                  count={board.lineup.team1.length}
                  api={api}
                  onSaved={onTeamSaved}
                  over={board.hot === 'team1'}
                />
                <span />
                <TeamHead
                  area="team2"
                  team={teamOf(2)}
                  count={board.lineup.team2.length}
                  api={api}
                  onSaved={onTeamSaved}
                  over={board.hot === 'team2'}
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
            </div>
            {rows.length === 0 && <p className="muted">Перетащите игроков в команды или нажмите →1 и →2.</p>}
          </section>
        </div>
      </LayoutGroup>
      </MotionConfig>
      {drag !== null && (
        <div
          className={`tm-float${refused ? ' refused' : ''}`}
          aria-hidden="true"
          style={{
            width: drag.width,
            height: drag.height,
            transform: `translate3d(${drag.x - drag.offsetX}px, ${drag.y - drag.offsetY}px, 0)`,
          }}
        >
          <Grip />
          <strong>{drag.code}</strong>
          {server.people.get(drag.code)?.name && (
            <span className="tm-name">{server.people.get(drag.code)?.name}</span>
          )}
        </div>
      )}
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
  // Ответ на сохранение приходит позже: привязываем его к самым свежим данным, а не к тем, что были при клике
  // (иначе фоновое обновление, закончившееся во время запроса, отбросило бы ответ и показало устаревший состав).
  const latest = useRef({ data: teams.data, current })
  useEffect(() => {
    latest.current = { data: teams.data, current }
  })

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
          onAssigned={(saved) => setOverride({ base: latest.current.data, teams: saved })}
          onFailed={reloadAll}
          onTeamSaved={(saved) => {
            const { data, current: shown } = latest.current
            if (!shown) return
            setOverride({
              base: data,
              teams: { teams: shown.teams.map((t) => (t.id === saved.id ? { ...t, ...saved } : t)) },
            })
          }}
        />
      )}
    </section>
  )
}
