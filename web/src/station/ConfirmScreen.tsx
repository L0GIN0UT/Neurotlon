import { motion } from 'motion/react'
import type { CSSProperties } from 'react'
import { DisciplineIcon } from '../shared/icons/DisciplineIcon.tsx'
import { Chip } from './Frame.tsx'
import { Icon } from './Icon.tsx'
import type { IconName } from './Icon.tsx'
import { initials, playerName, teamColor } from './model.ts'
import * as t from './texts.ts'
import type { CandidateView, Command } from './types.ts'

interface Props {
  candidate: CandidateView
  taken: CandidateView[]
  notice: string | null
  isLast: boolean
  discipline: string
  playersNeeded: number
  send: (command: Command) => void
}

function warnings(candidate: CandidateView, notice: string | null) {
  const items: { text: string; tone: 'warn' | 'bad'; icon: IconName }[] = []
  if (candidate.offline) items.push({ text: t.OFFLINE_WARNING, tone: 'warn', icon: 'offline' })
  for (const issue of candidate.issues) {
    items.push({ text: t.ISSUES[issue] ?? issue, tone: 'warn', icon: 'warning' })
  }
  if (notice) items.push({ text: notice, tone: 'bad', icon: 'warning' })
  return items.slice(0, 4)
}

/** Страница участника, как страница установленной игры в библиотеке: баннер команды и «Играть». */
export function ConfirmScreen({
  candidate,
  taken,
  notice,
  isLast,
  discipline,
  playersNeeded,
  send,
}: Props) {
  const style = { '--team': teamColor(candidate) } as CSSProperties
  const items = warnings(candidate, notice)
  return (
    <div className="confirm" style={style}>
      <motion.div
        className="banner"
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', visualDuration: 0.55, bounce: 0.18 }}
      >
        <div className="banner-glyph" aria-hidden>
          <DisciplineIcon discipline={discipline} />
        </div>
        <motion.div
          className="avatar"
          initial={{ scale: 0.4, rotate: -12 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ type: 'spring', stiffness: 260, damping: 16, delay: 0.12 }}
        >
          {initials(candidate.display_name, candidate.code)}
        </motion.div>
        <div className="banner-text">
          {playersNeeded === 2 && (
            <span className="banner-slot">
              {t.SLOT[taken.length]} · {t.SIDE[taken.length]}
            </span>
          )}
          <h1 className="banner-name">{playerName(candidate)}</h1>
          <p className="banner-team">
            {candidate.team ? t.teamLine(candidate.team.number, candidate.team.name) : t.TEAM_NONE}
          </p>
        </div>
      </motion.div>

      <div className="strip card">
        <motion.button
          type="button"
          className={`play ${candidate.warned ? 'play-warn' : ''}`}
          onClick={() => send({ action: 'confirm' })}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.97 }}
          data-testid="play"
        >
          <Icon name={isLast ? 'play' : 'arrow'} />
          {isLast ? t.PLAY : t.PLAY_NEXT}
        </motion.button>
        <dl className="info">
          <div>
            <dt>{t.INFO.participant}</dt>
            <dd>{candidate.code}</dd>
          </div>
          <div>
            <dt>{t.INFO.team}</dt>
            <dd>{candidate.team?.name ?? '—'}</dd>
          </div>
          <div>
            <dt>{t.INFO.discipline}</dt>
            <dd>{t.DISCIPLINE_NAMES[discipline] ?? discipline}</dd>
          </div>
        </dl>
        <button type="button" className="ghost" onClick={() => send({ action: 'cancel' })}>
          {t.NOT_ME}
        </button>
      </div>

      <div className="warnings">
        {items.map((item) => (
          <motion.div key={item.text} initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }}>
            <Chip tone={item.tone} icon={item.icon}>
              {item.text}
            </Chip>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
