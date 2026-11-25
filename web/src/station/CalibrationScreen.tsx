import { useMemo } from 'react'
import type { BridgeConfig } from './bridge.ts'
import {
  activeStep,
  failedSignals,
  isPong,
  partOf,
  phaseHint,
  phaseWord,
  secondsLeft,
  segmentFills,
  sensorText,
  sensorTone,
  statusText,
  stepFor,
  stepSubtitle,
  stepTitle,
  trackSignals,
} from './calibration.ts'
import type { CalibratingState } from './calibration.ts'
import { Chip } from './Frame.tsx'
import { Icon } from './Icon.tsx'
import { playerName } from './model.ts'
import { SignalChart } from './SignalChart.tsx'
import * as t from './texts.ts'
import type { CalibrationStepView, CandidateView, Command } from './types.ts'
import { useSignalStream } from './useSignalStream.ts'

type Send = (command: Command) => void

const RING = 2 * Math.PI * 9

/** Кольцо прогресса шага: идёт, готово (галочка) или сбой (крест). */
function StepRing({ step }: { step: CalibrationStepView }) {
  if (step.status === 'done') {
    return (
      <span className="ring ring-done" aria-hidden>
        <Icon name="check" />
      </span>
    )
  }
  if (step.status === 'failed') {
    return (
      <span className="ring ring-failed" aria-hidden>
        <Icon name="x" />
      </span>
    )
  }
  const progress = step.status === 'running' ? Math.min(1, Math.max(0, step.progress)) : 0
  return (
    <span className={`ring ring-${step.status}`} aria-hidden>
      <svg viewBox="0 0 24 24">
        <circle className="ring-track" cx="12" cy="12" r="9" />
        <circle
          className="ring-value"
          cx="12"
          cy="12"
          r="9"
          strokeDasharray={RING}
          strokeDashoffset={RING * (1 - progress)}
        />
      </svg>
    </span>
  )
}

function StepCard({
  step,
  active,
  send,
}: {
  step: CalibrationStepView
  active: boolean
  send: Send
}) {
  return (
    <li
      className={`step-card step-card-${step.status}${active ? ' step-card-active' : ''}`}
      aria-current={active ? 'step' : undefined}
      data-status={step.status}
    >
      <StepRing step={step} />
      <div className="step-card-text">
        <strong>{stepTitle(step)}</strong>
        <span className="step-card-status">{statusText(step)}</span>
      </div>
      {step.status === 'failed' && (
        <button
          type="button"
          className="mini-button"
          onClick={() => send({ action: 'calibration_retry', value: step.id })}
        >
          {t.CALIB.retry}
        </button>
      )}
    </li>
  )
}

/** Полоса из сегментов шага; цвет сегмента — напряжение или расслабление. */
function SegmentBar({ step }: { step: CalibrationStepView }) {
  return (
    <div className="segments" aria-hidden>
      {segmentFills(step).map((segment, i) => (
        <span key={i} className={`segment segment-${segment.tone}${segment.current ? ' segment-current' : ''}`}>
          <i style={{ transform: `scaleX(${segment.fill})` }} />
        </span>
      ))}
    </div>
  )
}

function Countdown({ step }: { step: CalibrationStepView }) {
  const left = secondsLeft(step)
  if (left === null) return null
  return (
    <div className="phase-count" data-testid="countdown">
      <span>{left}</span>
      <small>{t.CALIB.secondsShort}</small>
    </div>
  )
}

function PlayerLane({
  player,
  index,
  signal,
  state,
  step,
}: {
  player: CandidateView | undefined
  index: number
  signal: string
  state: CalibratingState
  step: CalibrationStepView
}) {
  const sensor = state.sensors.find((s) => s.signal === signal)
  const part = partOf(step, signal)
  return (
    <div className="pong-lane card">
      <span className="pong-lane-side">
        {t.CALIB.player(index + 1)} · {t.CALIB.playerSide[index]}
      </span>
      <strong>{player ? playerName(player) : t.CALIB.trackNames[signal]}</strong>
      {sensor && (
        <Chip tone={sensorTone(sensor)} icon="dot">
          {sensorText(sensor)}
        </Chip>
      )}
      {part.status === 'done' && <span className="pong-lane-result good">{t.CALIB.statusDone}</span>}
      {part.status === 'failed' && (
        <span className="pong-lane-result bad">{part.reason_text?.trim() || t.CALIB.failedDefault}</span>
      )}
    </div>
  )
}

/** Центр экрана, пока шаг идёт: что делать участнику и сколько осталось. */
function StepPanel({ step, state }: { step: CalibrationStepView; state: CalibratingState }) {
  if (step.step === 'baseline') {
    return (
      <div className="phase phase-baseline">
        <span className="baseline-dot" aria-hidden />
        <div className="phase-live" aria-live="polite" aria-atomic="true">
          <p className="phase-word phase-word-baseline">{t.CALIB.baselineLook}</p>
        </div>
        <p className="phase-hint">{t.CALIB.baselineHint}</p>
        <Countdown step={step} />
      </div>
    )
  }
  const mood = step.status === 'running' && step.phase ? step.phase : 'wait'
  return (
    <div className={`phase phase-${mood}`}>
      <div className="phase-live" aria-live="polite" aria-atomic="true">
        <p className="phase-word">{phaseWord(step)}</p>
      </div>
      <p className="phase-hint">{phaseHint(step)}</p>
      <Countdown step={step} />
      <SegmentBar step={step} />
      {isPong(state.steps) && (
        <div className="pong-lanes">
          <PlayerLane player={state.players[0]} index={0} signal="emg_left" state={state} step={step} />
          <PlayerLane player={state.players[1]} index={1} signal="emg_right" state={state} step={step} />
        </div>
      )}
    </div>
  )
}

function BackButton({ send }: { send: Send }) {
  return (
    <button type="button" className="ghost" onClick={() => send({ action: 'back' })}>
      <Icon name="back" />
      {t.BACK}
    </button>
  )
}

/** Сбой шага: красная плашка с причиной, «Повторить» (в понге — по игроку) и «Назад». */
function FailedPanel({ step, send }: { step: CalibrationStepView; send: Send }) {
  const perPlayer = step.signals.length > 1
  const failed = failedSignals(step)
  const targets = perPlayer ? (failed.length > 0 ? failed : step.signals) : []
  return (
    <div className="calib-fail" role="alert">
      <span className="badge badge-bad">
        <Icon name="x" />
      </span>
      <h2>{t.CALIB.failedTitle}</h2>
      {perPlayer ? (
        <ul className="calib-fail-list">
          {targets.map((signal) => (
            <li key={signal} className="calib-fail-reason card">
              <strong>{t.CALIB.player(step.signals.indexOf(signal) + 1)}</strong>
              {partOf(step, signal).reason_text?.trim() || t.CALIB.failedDefault}
            </li>
          ))}
        </ul>
      ) : (
        <p className="calib-fail-reason card">{statusText(step)}</p>
      )}
      <div className="calib-actions">
        <BackButton send={send} />
        {perPlayer ? (
          targets.map((signal, i) => (
            <button
              key={signal}
              type="button"
              className="ghost"
              data-primary={i === 0 ? '' : undefined}
              autoFocus={i === 0}
              onClick={() => send({ action: 'calibration_retry', value: signal })}
            >
              {t.CALIB.recalibratePlayer(step.signals.indexOf(signal) + 1)}
            </button>
          ))
        ) : (
          <button
            type="button"
            className="go"
            data-primary=""
            autoFocus
            onClick={() => send({ action: 'calibration_retry', value: step.id })}
          >
            {t.CALIB.retry}
          </button>
        )}
      </div>
    </div>
  )
}

function LostPanel({ send }: { send: Send }) {
  return (
    <div className="calib-fail" role="alert">
      <span className="badge badge-bad">
        <Icon name="offline" />
      </span>
      <h2>{t.CALIB.link.lost}</h2>
      <p className="calib-fail-reason card">{t.CALIB.linkLostHint}</p>
      <div className="calib-actions">
        <BackButton send={send} />
        <button
          type="button"
          className="go"
          data-primary=""
          autoFocus
          onClick={() => send({ action: 'calibration_restart' })}
        >
          {t.CALIB.retry}
        </button>
      </div>
    </div>
  )
}

/** Проверка сигнала: живой график, подсказки и решение волонтёра. */
function CheckPanel({
  state,
  config,
  send,
}: {
  state: CalibratingState
  config: BridgeConfig
  send: Send
}) {
  const { store } = useSignalStream(config)
  const tracks = useMemo(() => trackSignals(state.steps), [state.steps])
  const pong = isPong(state.steps)
  const muscle = stepFor(state.steps, (s) => s.startsWith('emg'))
  const brain = stepFor(state.steps, (s) => s === 'eeg')
  const tips = [
    ...(tracks.some((s) => s.startsWith('emg')) ? [t.CALIB.tipEmg] : []),
    ...(tracks.includes('eeg') ? [t.CALIB.tipEeg] : []),
  ]
  return (
    <div className="check">
      <header className="check-head">
        <h2 aria-live="polite">{t.CALIB.checkTitle}</h2>
        <p>{t.CALIB.checkLead}</p>
      </header>
      <div className="check-chart card">
        <SignalChart store={store} tracks={tracks} label={t.CALIB.checkTitle} />
      </div>
      <ul className="check-tips">
        {tips.map((tip) => (
          <li key={tip}>{tip}</li>
        ))}
      </ul>
      <div className="calib-actions">
        <div className="calib-actions-side">
          {pong
            ? muscle?.signals.map((signal, i) => (
                <button
                  key={signal}
                  type="button"
                  className="ghost slim"
                  onClick={() => send({ action: 'calibration_retry', value: signal })}
                >
                  {t.CALIB.recalibratePlayer(i + 1)}
                </button>
              ))
            : muscle && (
                <button
                  type="button"
                  className="ghost slim"
                  onClick={() => send({ action: 'calibration_retry', value: muscle.id })}
                >
                  {t.CALIB.recalibrateMuscle}
                </button>
              )}
          {brain && (
            <button
              type="button"
              className="ghost slim"
              onClick={() => send({ action: 'calibration_retry', value: brain.id })}
            >
              {t.CALIB.recalibrateBrain}
            </button>
          )}
        </div>
        <div className="calib-actions-side">
          <BackButton send={send} />
          <button
            type="button"
            className="go"
            data-primary=""
            autoFocus
            onClick={() => send({ action: 'calibration_continue' })}
          >
            {t.CALIB.proceed}
            <Icon name="arrow" />
          </button>
        </div>
      </div>
    </div>
  )
}

function TopChips({ state }: { state: CalibratingState }) {
  const method = state.eeg_method ? (t.CALIB.eegMethods[state.eeg_method] ?? state.eeg_method) : null
  return (
    <div className="calib-chips">
      {state.sensors.map((sensor) => (
        <Chip key={sensor.signal} tone={sensorTone(sensor)} icon="dot">
          {sensorText(sensor)}
        </Chip>
      ))}
      {method && state.steps.some((s) => s.signals.includes('eeg')) && (
        <Chip tone="muted">{`${t.CALIB.methodLabel}: ${method}`}</Chip>
      )}
    </div>
  )
}

/** Экран «Калибровка»: шаги слева, активный шаг или проверка сигнала в центре. */
export function CalibrationScreen({
  state,
  config,
  send,
}: {
  state: CalibratingState
  config: BridgeConfig
  send: Send
}) {
  const active = activeStep(state)
  const failed = state.steps.find((s) => s.status === 'failed')
  const lost = state.link === 'lost'

  let main
  if (lost) main = <LostPanel send={send} />
  else if (failed) main = <FailedPanel step={failed} send={send} />
  else if (state.ready) main = <CheckPanel state={state} config={config} send={send} />
  else if (active) {
    main = (
      <div className="calib-running">
        <StepPanel step={active} state={state} />
        <div className="calib-actions calib-actions-end">
          <BackButton send={send} />
        </div>
      </div>
    )
  } else {
    main = (
      <div className="calib-running">
        <div className="spinner" aria-hidden />
        <p className="lead">{t.CALIB.link.connecting}</p>
      </div>
    )
  }

  return (
    <div className="calib" data-link={state.link}>
      <header className="calib-top">
        <h1>{t.CALIB.title}</h1>
        <TopChips state={state} />
      </header>
      <div className="calib-body">
        <ol className="calib-steps" aria-label={t.CALIB.steps}>
          {state.steps.map((step) => (
            <StepCard key={step.id} step={step} active={step === active && !state.ready} send={send} />
          ))}
        </ol>
        <section className="calib-main">{main}</section>
      </div>
      {active && !state.ready && !failed && !lost && (
        <p className="sr-only" role="status">
          {`${stepTitle(active)}: ${statusText(active)}. ${stepSubtitle(active)}`}
        </p>
      )}
    </div>
  )
}
