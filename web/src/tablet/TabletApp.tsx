import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { ApiError, NetworkError, createApi } from './api.ts'
import type { Api, DisciplineConfig, Me } from './api.ts'
import { clearCached, loadCached, saveCached } from './cache.ts'
import { CheckStep } from './components/CheckStep.tsx'
import { DoneStep } from './components/DoneStep.tsx'
import type { Recorded } from './components/DoneStep.tsx'
import { EntryStep } from './components/EntryStep.tsx'
import { Login } from './components/Login.tsx'
import { ParticipantStep } from './components/ParticipantStep.tsx'
import { QueuePanel } from './components/QueuePanel.tsx'
import { SummaryStep } from './components/SummaryStep.tsx'
import { emptyDraft } from './entryForm.ts'
import type { EntryDraft } from './entryForm.ts'
import { createIdbStore } from './idbStore.ts'
import { DISCIPLINE_NAMES, errorText } from './messages.ts'
import { classifyFailure, createOfflineQueue, makeSender } from './offlineQueue.ts'
import type { QueueStore } from './offlineQueue.ts'
import { PayloadError, buildSubmission } from './payload.ts'
import type { EntryInput } from './payload.ts'
import type { Person } from './people.ts'
import { newSessionId } from './uuid.ts'
import './tablet.css'

type Auth =
  | { status: 'loading' }
  | { status: 'anon' }
  | { status: 'forbidden'; me: Me }
  | { status: 'error'; message: string }
  | { status: 'ready'; me: Me; config: DisciplineConfig }

type Flow =
  | { step: 'participants' }
  | { step: 'check'; codes: string[] }
  | { step: 'entry'; people: Person[]; sessionId: string; draft: EntryDraft }
  | {
      step: 'summary'
      people: Person[]
      sessionId: string
      draft: EntryDraft
      entries: EntryInput[]
      winner: string | null
    }
  | { step: 'done'; people: Person[]; result: Recorded }

interface Props {
  fetchFn?: typeof fetch
  store?: QueueStore
}

/** Кто вошёл и какая у него секция; null — сессии нет (401, вход покажет onUnauthorized). */
async function resolveAuth(api: Api): Promise<Auth | null> {
  let me: Me | undefined
  try {
    me = await api.me()
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null
    me = e instanceof NetworkError ? loadCached().me : undefined
    if (!me) return { status: 'error', message: errorText(e) }
  }
  if (me.role !== 'volunteer' || me.discipline === null) return { status: 'forbidden', me }
  try {
    const config = await api.config()
    saveCached({ me, config })
    return { status: 'ready', me, config }
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null
    const cached = loadCached()
    if (cached.me?.login === me.login && cached.config) {
      return { status: 'ready', me, config: cached.config }
    }
    return { status: 'error', message: errorText(e) }
  }
}

export function TabletApp({ fetchFn, store }: Props) {
  const [auth, setAuth] = useState<Auth>({ status: 'loading' })
  const [api] = useState<Api>(() =>
    createApi({ fetchFn, onUnauthorized: () => setAuth({ status: 'anon' }) }),
  )
  const [queue] = useState(() =>
    createOfflineQueue(store ?? createIdbStore(), makeSender(api)),
  )
  const snapshot = useSyncExternalStore(queue.subscribe, queue.getSnapshot)

  const reload = useCallback(() => {
    setAuth({ status: 'loading' })
    void resolveAuth(api).then((next) => {
      if (next) setAuth(next)
    })
  }, [api])

  useEffect(() => {
    let active = true
    void resolveAuth(api).then((next) => {
      if (active && next) setAuth(next)
    })
    return () => {
      active = false
    }
  }, [api])

  const ready = auth.status === 'ready'
  useEffect(() => {
    if (!ready) return
    return queue.start()
  }, [ready, queue])

  async function logout() {
    try {
      await api.logout()
    } catch {
      // сессия всё равно забывается на планшете
    }
    clearCached()
    setAuth({ status: 'anon' })
  }

  return (
    <main className="tablet">
      {auth.status === 'loading' && <p className="card">Загрузка…</p>}
      {auth.status === 'anon' && <Login api={api} onLoggedIn={reload} />}
      {auth.status === 'error' && (
        <section className="card stack">
          <p role="alert" className="error">
            {auth.message}
          </p>
          <button type="button" className="primary" onClick={reload}>
            Повторить
          </button>
        </section>
      )}
      {auth.status === 'forbidden' && (
        <section className="card stack">
          <h1>Только для волонтёров</h1>
          <p>Учётная запись «{auth.me.login}» не подходит для планшета. Войдите как волонтёр.</p>
          <button type="button" className="primary" onClick={() => void logout()}>
            Выйти
          </button>
        </section>
      )}
      {auth.status === 'ready' && (
        <>
          <header className="topbar">
            <strong>{DISCIPLINE_NAMES[auth.config.discipline]}</strong>
            <span>{auth.me.login}</span>
            <QueuePanel queue={queue} snapshot={snapshot} />
            <button type="button" onClick={() => void logout()}>
              Выйти
            </button>
          </header>
          <Flow api={api} queue={queue} config={auth.config} />
        </>
      )}
    </main>
  )
}

interface FlowProps {
  api: Api
  queue: ReturnType<typeof createOfflineQueue>
  config: DisciplineConfig
}

function Flow({ api, queue, config }: FlowProps) {
  const [flow, setFlow] = useState<Flow>({ step: 'participants' })
  const [busy, setBusy] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { discipline, section } = config

  function startEntry(people: Person[]) {
    setFlow({ step: 'entry', people, sessionId: newSessionId(), draft: emptyDraft(people) })
  }

  async function record(
    current: Extract<Flow, { step: 'summary' }>,
  ): Promise<void> {
    setBusy(true)
    setSubmitError(null)
    try {
      const payload = buildSubmission({
        sessionId: current.sessionId,
        discipline,
        section,
        finishedAt: new Date(),
        entries: current.entries,
        winner: current.winner,
      })
      try {
        const receipt = await api.submitResult(payload)
        setFlow({
          step: 'done',
          people: current.people,
          result: {
            kind: 'recorded',
            sessionId: current.sessionId,
            recordedAt: Date.now(),
            receipt,
          },
        })
      } catch (e) {
        const failure = classifyFailure(e)
        if (failure.kind === 'retry') {
          await queue.enqueue(payload)
          setFlow({
            step: 'done',
            people: current.people,
            result: { kind: 'queued', sessionId: current.sessionId },
          })
        } else {
          await queue.reject(payload, failure.message)
          setSubmitError(`Сервер отклонил результат: ${failure.message}. Он в списке «Ошибки».`)
        }
      }
    } catch (e) {
      setSubmitError(e instanceof PayloadError ? e.message : errorText(e))
    } finally {
      setBusy(false)
    }
  }

  switch (flow.step) {
    case 'participants':
      return (
        <ParticipantStep
          slots={discipline === 'pong' ? 2 : 1}
          onNext={(codes) => setFlow({ step: 'check', codes })}
        />
      )
    case 'check':
      return (
        <CheckStep
          api={api}
          discipline={discipline}
          section={section}
          codes={flow.codes}
          onBack={() => setFlow({ step: 'participants' })}
          onContinue={startEntry}
        />
      )
    case 'entry':
      return (
        <EntryStep
          discipline={discipline}
          people={flow.people}
          durationS={config.duration_s}
          draft={flow.draft}
          onDraft={(draft) => setFlow({ ...flow, draft })}
          onBack={() => setFlow({ step: 'check', codes: flow.people.map((p) => p.code) })}
          onNext={(entries, winner) => {
            setSubmitError(null)
            setFlow({
              step: 'summary',
              people: flow.people,
              sessionId: flow.sessionId,
              draft: flow.draft,
              entries,
              winner,
            })
          }}
        />
      )
    case 'summary':
      return (
        <SummaryStep
          discipline={discipline}
          people={flow.people}
          entries={flow.entries}
          winner={flow.winner}
          busy={busy}
          error={submitError}
          onBack={() =>
            setFlow({
              step: 'entry',
              people: flow.people,
              sessionId: flow.sessionId,
              draft: flow.draft,
            })
          }
          onSubmit={() => void record(flow)}
          onRestart={() => {
            setSubmitError(null)
            setFlow({ step: 'participants' })
          }}
        />
      )
    case 'done':
      return (
        <DoneStep
          api={api}
          result={flow.result}
          onNext={() => setFlow({ step: 'participants' })}
          onRedo={() => startEntry(flow.people)}
        />
      )
  }
}
