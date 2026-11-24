import { motion } from 'motion/react'
import { DisciplineIcon } from '../shared/icons/DisciplineIcon.tsx'
import { Chip } from './Frame.tsx'
import { Icon } from './Icon.tsx'
import { playerName, teamColor } from './model.ts'
import * as t from './texts.ts'
import type { CandidateView, Command, RejectedItem } from './types.ts'

function Players({ players }: { players: CandidateView[] }) {
  return (
    <div className="players">
      {players.map((player) => (
        <span key={player.code} className="player-pill" style={{ borderColor: teamColor(player) }}>
          <i style={{ background: teamColor(player) }} />
          {playerName(player)}
        </span>
      ))}
    </div>
  )
}

/** Шаг назад: проверка, запуск, игра и проблема. Игру, если она идёт, останавливает. */
function BackButton({
  send,
  inline = false,
}: {
  send: (command: Command) => void
  inline?: boolean
}) {
  return (
    <button
      type="button"
      className={`ghost wide back-button${inline ? ' inline' : ''}`}
      onClick={() => send({ action: 'back' })}
    >
      <Icon name="back" />
      {t.BACK}
    </button>
  )
}

/** «Проверяем участника» и «Запускаем игру»: вращающееся кольцо и подпись. */
export function BusyScreen({
  title,
  hint,
  players,
  send,
}: {
  title: string
  hint?: string
  players: CandidateView[]
  send: (command: Command) => void
}) {
  return (
    <div className="center">
      <div className="spinner" aria-hidden />
      <h1 className="big">{title}</h1>
      {hint && <p className="lead">{hint}</p>}
      {players.length > 0 && <Players players={players} />}
      <BackButton send={send} />
    </div>
  )
}

export function PlayingScreen({
  players,
  discipline,
  offline,
  defaultLimit,
  send,
}: {
  players: CandidateView[]
  discipline: string
  offline: boolean
  defaultLimit: boolean
  send: (command: Command) => void
}) {
  return (
    <div className="center">
      <div className="pulse">
        <DisciplineIcon discipline={discipline} />
      </div>
      <h1 className="big">{t.PLAYING}</h1>
      <p className="lead">{t.PLAYING_HINT}</p>
      <Players players={players} />
      <div className="stack">
        {offline && (
          <Chip tone="warn" icon="offline">
            {t.PLAYING_OFFLINE}
          </Chip>
        )}
        {defaultLimit && (
          <Chip tone="warn" icon="info">
            {t.LIMIT_DEFAULT}
          </Chip>
        )}
      </div>
      <BackButton send={send} />
    </div>
  )
}

export function DoneScreen({
  lines,
  secondsLeft,
  secondsTotal,
}: {
  lines: string[]
  secondsLeft: number
  secondsTotal: number
}) {
  return (
    <div className="center">
      <motion.div
        className="done-mark"
        initial={{ scale: 0.5, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 220, damping: 14 }}
      >
        <svg viewBox="0 0 24 24" aria-hidden>
          <motion.path
            d="M5 12l5 5l10 -10"
            fill="none"
            strokeWidth={2.4}
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ delay: 0.2, duration: 0.4, ease: 'easeOut' }}
          />
        </svg>
      </motion.div>
      <h1 className="big">{t.DONE}</h1>
      <ul className="results card">
        {lines.map((line, i) => {
          const { label, value } = splitResult(line)
          return (
            <motion.li
              key={line}
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.25 + i * 0.1 }}
            >
              <span className="results-label">{label}</span>
              {value && (
                <span className={`results-value ${value.includes(t.POINTS_UNIT) ? 'good' : 'warn'}`}>
                  {value}
                </span>
              )}
            </motion.li>
          )
        })}
      </ul>
      <div className="countdown" aria-hidden>
        <motion.span
          initial={{ scaleX: secondsTotal > 0 ? secondsLeft / secondsTotal : 0 }}
          animate={{ scaleX: 0 }}
          transition={{ duration: secondsLeft, ease: 'linear' }}
        />
      </div>
    </div>
  )
}

const splitResult = t.splitResultLine

export function ProblemScreen({
  reason,
  send,
}: {
  reason: string
  send: (command: Command) => void
}) {
  return (
    <div className="center">
      <div className="badge badge-warn">
        <Icon name="warning" />
      </div>
      <h1 className="big">{t.PROBLEM}</h1>
      <p className="lead">{t.PROBLEM_HINT}</p>
      <p className="reason card">{reason}</p>
      <div className="actions">
        <BackButton send={send} inline />
        <button type="button" className="play play-warn" onClick={() => send({ action: 'retry' })}>
          {t.RETRY}
        </button>
      </div>
    </div>
  )
}

export function BlockedScreen({ message }: { message: string }) {
  return (
    <div className="center">
      <div className="badge badge-bad">
        <Icon name="x" />
      </div>
      <h1 className="big">{t.BLOCKED}</h1>
      <p className="lead lead-bad">{t.BLOCKED_CALL}</p>
      <p className="reason card reason-bad">{message}</p>
      <p className="lead small">{t.BLOCKED_HINT}</p>
    </div>
  )
}

export function RejectedScreen({
  items,
  exportedTo,
  send,
}: {
  items: RejectedItem[]
  exportedTo: string | null
  send: (command: Command) => void
}) {
  return (
    <div className="rejected">
      <h1 className="rejected-title">{t.REJECTED_TITLE}</h1>
      <p className="lead">{t.REJECTED_HINT}</p>
      <div className="table card">
        {items.length === 0 ? (
          <p className="empty">{t.REJECTED_EMPTY}</p>
        ) : (
          <table>
            <thead>
              <tr>
                {t.REJECTED_COLUMNS.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 8).map((item) => (
                <tr key={item.session_id}>
                  <td>{item.session_id.slice(0, 8)}</td>
                  <td>{item.codes.join(', ')}</td>
                  <td className="warn">{item.error}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="rejected-actions">
        {exportedTo && <span className="good">{t.exportedTo(exportedTo)}</span>}
        <button type="button" className="play" onClick={() => send({ action: 'export_rejected' })}>
          {t.EXPORT}
        </button>
        <button type="button" className="ghost wide" onClick={() => send({ action: 'close_rejected' })}>
          {t.BACK}
        </button>
      </div>
    </div>
  )
}
