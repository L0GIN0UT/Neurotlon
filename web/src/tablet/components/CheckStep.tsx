import { useEffect, useState } from 'react'
import { ApiError } from '../api.ts'
import type { Api, Discipline, Eligibility, Section } from '../api.ts'
import { ISSUE_TEXTS } from '../messages.ts'
import { personLabel } from '../people.ts'
import type { Person } from '../people.ts'

type Lookup =
  | { state: 'loading' }
  | { state: 'ok'; info: Eligibility }
  | { state: 'unknown' }
  | { state: 'offline' }

interface Props {
  api: Api
  discipline: Discipline
  section: Section
  codes: string[]
  onBack: () => void
  onContinue: (people: Person[]) => void
}

export function CheckStep({ api, discipline, section, codes, onBack, onContinue }: Props) {
  const [lookups, setLookups] = useState<Record<string, Lookup>>({})

  useEffect(() => {
    let cancelled = false
    for (const code of codes) {
      api
        .eligibility(code, discipline, section)
        .then((info): Lookup => ({ state: 'ok', info }))
        .catch((e: unknown): Lookup =>
          e instanceof ApiError && e.status === 404 ? { state: 'unknown' } : { state: 'offline' },
        )
        .then((lookup) => {
          if (!cancelled) setLookups((prev) => ({ ...prev, [code]: lookup }))
        })
    }
    return () => {
      cancelled = true
    }
  }, [api, codes, discipline, section])

  const states = codes.map((code) => lookups[code] ?? ({ state: 'loading' } as Lookup))
  const ready = states.every((s) => s.state !== 'loading')
  const blocked = states.some((s) => s.state === 'unknown')

  function next() {
    onContinue(
      codes.map((code, index) => {
        const lookup = states[index]
        return { code, info: lookup?.state === 'ok' ? lookup.info : null }
      }),
    )
  }

  return (
    <section className="card stack">
      <h1>Проверка</h1>
      {codes.map((code, index) => {
        const lookup = states[index]
        return (
          <article key={code} className={`person ${personClass(lookup)}`}>
            <h2>{lookup?.state === 'ok' ? personLabel({ code, info: lookup.info }) : code}</h2>
            {lookup?.state === 'loading' && <p>Проверяем…</p>}
            {lookup?.state === 'unknown' && (
              <p role="alert" className="error">
                Участник с таким ID не найден
              </p>
            )}
            {lookup?.state === 'offline' && (
              <p className="warning">Нет связи, проверка пропущена. Можно продолжить.</p>
            )}
            {lookup?.state === 'ok' && <EligibilityView info={lookup.info} />}
          </article>
        )
      })}
      <div className="row">
        <button type="button" onClick={onBack}>
          Назад
        </button>
        <button type="button" className="primary" disabled={!ready || blocked} onClick={next}>
          Продолжить
        </button>
      </div>
    </section>
  )
}

function personClass(lookup: Lookup | undefined): string {
  if (lookup?.state === 'unknown') return 'bad'
  if (lookup?.state === 'ok' && lookup.info.issues.length > 0) return 'warn'
  return ''
}

function EligibilityView({ info }: { info: Eligibility }) {
  return (
    <>
      {info.team ? (
        <p className="team">
          <span className="swatch" style={{ background: info.team.color }} aria-hidden="true" />
          Команда {info.team.number}: {info.team.name}
        </p>
      ) : (
        <p className="team">Команда ещё не назначена</p>
      )}
      {info.issues.length > 0 && (
        <ul className="warning" aria-label="Предупреждения">
          {info.issues.map((issue) => (
            <li key={issue}>{ISSUE_TEXTS[issue]}</li>
          ))}
        </ul>
      )}
    </>
  )
}
