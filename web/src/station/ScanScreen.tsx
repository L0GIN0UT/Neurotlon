import { motion } from 'motion/react'
import { normalizeCode } from '../tablet/participantCode.ts'
import { Chip } from './Frame.tsx'
import { Icon } from './Icon.tsx'
import { playerName, teamColor } from './model.ts'
import * as t from './texts.ts'
import type { CandidateView, Command } from './types.ts'
import { useQrCamera } from './useQrCamera.ts'

const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

function Camera({ onCode, name }: { onCode: (text: string) => void; name: string | null }) {
  const { videoRef, state } = useQrCamera(onCode, true, name)
  return (
    <div className="camera card" data-state={state}>
      <video ref={videoRef} muted playsInline className={state === 'live' ? 'live' : ''} />
      {state === 'live' && (
        <>
          <span className="bracket tl" />
          <span className="bracket tr" />
          <span className="bracket bl" />
          <span className="bracket br" />
          <motion.span
            className="scanline"
            animate={{ top: ['8%', '88%', '8%'] }}
            transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
          />
        </>
      )}
      {state === 'starting' && <p className="camera-note">{t.CAMERA_STARTING}</p>}
      {state === 'unavailable' && (
        <div className="camera-note">
          <Icon name="warning" className="camera-icon" />
          <strong>{t.NO_CAMERA}</strong>
          <span>{t.NO_CAMERA_HINT}</span>
        </div>
      )}
    </div>
  )
}

function Slot({
  index,
  taken,
  active,
}: {
  index: number
  taken: CandidateView | undefined
  active: boolean
}) {
  return (
    <div
      className={`slot card ${active ? 'slot-active' : ''}`}
      style={taken ? { borderColor: teamColor(taken) } : undefined}
    >
      <span className="slot-label">
        {t.SLOT[index]} · {t.SIDE[index]}
      </span>
      {taken ? (
        <span className="slot-name">
          <i style={{ background: teamColor(taken) }} />
          {playerName(taken)}
        </span>
      ) : (
        <span className="slot-wait">{t.SLOT_WAITING}</span>
      )}
    </div>
  )
}

interface Props {
  input: string
  notice: string | null
  taken: CandidateView[]
  playersNeeded: number
  camera: string | null
  send: (command: Command) => void
}

export function ScanScreen({ input, notice, taken, playersNeeded, camera, send }: Props) {
  const two = playersNeeded === 2
  const prompt = two ? (t.SCAN_PROMPT_PONG[taken.length] ?? t.SCAN_PROMPT) : t.SCAN_PROMPT
  const onCode = (text: string) => {
    if (normalizeCode(text) !== null) send({ action: 'enter_code', value: text })
  }
  return (
    <div className="scan">
      <Camera onCode={onCode} name={camera} />
      <div className="scan-side">
        <h1 className="scan-title">{prompt}</h1>
        {two && (
          <div className="slots">
            {[0, 1].map((i) => (
              <Slot key={i} index={i} taken={taken[i]} active={i === taken.length} />
            ))}
          </div>
        )}
        <p className="scan-or">{t.TYPE_HINT}</p>
        <div className={`field card ${input ? 'field-filled' : ''}`} data-testid="id-field">
          {input ? (
            <span className="field-text">
              {/^\d+$/.test(input) && <span className="field-prefix">NT</span>}
              {input}
              <i className="caret" />
            </span>
          ) : (
            <span className="field-placeholder">{t.ID_PLACEHOLDER}</span>
          )}
        </div>
        <div className="notice-row">
          {notice && (
            <motion.div key={notice} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>
              <Chip tone="bad" icon="warning">
                {notice}
              </Chip>
            </motion.div>
          )}
        </div>
        <div className="keypad">
          {DIGITS.map((digit) => (
            <button
              key={digit}
              type="button"
              className="key"
              onClick={() => send({ action: 'type_char', value: digit })}
            >
              {digit}
            </button>
          ))}
          <button
            type="button"
            className="key"
            aria-label="Стереть"
            onClick={() => send({ action: 'backspace' })}
          >
            <Icon name="backspace" />
          </button>
          <button
            type="button"
            className="key"
            onClick={() => send({ action: 'type_char', value: '0' })}
          >
            0
          </button>
          <button
            type="button"
            className="key key-primary"
            disabled={!input}
            onClick={() => send({ action: 'submit_input' })}
          >
            <Icon name="arrow" />
            {t.NEXT}
          </button>
        </div>
      </div>
    </div>
  )
}
