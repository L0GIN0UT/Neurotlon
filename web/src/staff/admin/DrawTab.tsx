import { useCallback, useState } from 'react'
import { ApiError } from '../../shared/http.ts'
import type { DrawProtocol, StaffApi } from '../api.ts'
import { ConfirmDialog, ErrorText } from '../ui.tsx'
import { formatTime } from '../format.ts'
import { useAction, useLoader } from '../hooks.ts'
import { TeamsEditor } from './TeamsEditor.tsx'

async function loadDraw(api: StaffApi): Promise<DrawProtocol | null> {
  try {
    return await api.draw()
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export function DrawTab({ api }: { api: StaffApi }) {
  const options = useLoader(() => api.drawOptions())
  const draw = useLoader(useCallback(() => loadDraw(api), [api]))
  const action = useAction()
  const [m, setM] = useState<number | null>(null)
  const [seed, setSeed] = useState('')
  const [confirming, setConfirming] = useState(false)

  const seedValue = seed.trim() === '' ? undefined : Number(seed)
  const seedInvalid = seedValue !== undefined && !Number.isSafeInteger(seedValue)
  const done = draw.data !== undefined && draw.data !== null

  async function run() {
    if (m === null) return
    const result = await action.run(() => api.runDraw(m, seedValue))
    setConfirming(false)
    if (result) {
      draw.reload()
      options.reload()
    }
  }

  return (
    <section className="stack">
      <div className="card stack no-print">
        <h2>Выбор размера команды</h2>
        {done && (
          <p className="warning">
            Жеребьёвка уже проведена. Повторить её может только суперпользователь и только пока нет
            результатов.
          </p>
        )}
        {options.data && options.data.length === 0 && (
          <p>Нет подходящих вариантов: отметьте участников обеих категорий.</p>
        )}
        {options.data && options.data.length > 0 && (
          <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Выбор</th>
                <th className="num">Человек в команде (m)</th>
                <th className="num">Команд</th>
                <th className="num">В резерве</th>
                <th className="num">Резерв с ОВЗ</th>
                <th className="num">Резерв без ОВЗ</th>
              </tr>
            </thead>
            <tbody>
              {options.data.map((option) => (
                <tr key={option.m}>
                  <td>
                    <input
                      type="radio"
                      name="m"
                      aria-label={`m = ${option.m}`}
                      checked={m === option.m}
                      onChange={() => setM(option.m)}
                    />
                  </td>
                  <td className="num">{option.m}</td>
                  <td className="num">{option.team_count}</td>
                  <td className="num">{option.reserve_total}</td>
                  <td className="num">{option.reserve_ovz}</td>
                  <td className="num">{option.reserve_general}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
        <label className="field">
          Зерно (необязательно, для повторяемости)
          <input
            inputMode="numeric"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="случайное"
          />
        </label>
        {seedInvalid && <p className="error">Зерно — целое число</p>}
        <ErrorText error={action.error ?? options.error ?? draw.error} />
        <button
          type="button"
          className="primary"
          disabled={m === null || seedInvalid || action.busy}
          onClick={() => setConfirming(true)}
        >
          Провести жеребьёвку
        </button>
      </div>

      {confirming && m !== null && (
        <ConfirmDialog
          title="Провести жеребьёвку?"
          message={`Размер команды m = ${m}. Составы и пары будут назначены и показаны на экранах.`}
          confirmLabel="Да, провести"
          busy={action.busy}
          onConfirm={() => void run()}
          onCancel={() => setConfirming(false)}
        />
      )}

      {draw.data && <TeamsEditor key={draw.data.id} api={api} onSaved={draw.reload} />}
      {draw.data && <Protocol protocol={draw.data} />}
    </section>
  )
}

/** Протокол для печати. Категория видна только здесь: резерв считается по категориям. */
function Protocol({ protocol }: { protocol: DrawProtocol }) {
  const teamName = (number: number) =>
    protocol.teams.find((t) => t.number === number)?.name ?? `Команда ${number}`
  return (
    <article className="card stack print-area" aria-label="Протокол жеребьёвки">
      <div className="row no-print">
        <h2 className="grow">Протокол жеребьёвки</h2>
        <button type="button" onClick={() => window.print()}>
          Печать протокола
        </button>
      </div>
      <h2 className="print-only">Нейротлон: протокол жеребьёвки</h2>
      <p>
        Зерно: <strong>{protocol.seed}</strong>, m = {protocol.m}, команд: {protocol.team_count},
        время: {formatTime(protocol.created_at)}
      </p>
      <div className="columns">
        {protocol.teams.map((team) => (
          <section key={team.number}>
            <h3>
              <span className="swatch" style={{ background: team.color }} />
              {team.name}
            </h3>
            <ol>
              {team.members.map((member) => (
                <li key={member.code} value={member.number_in_team}>
                  {member.code}
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
      <h3>Дуэли и пары</h3>
      {protocol.duels.map((duel) => (
        <section key={duel.order}>
          <h4>
            Дуэль {duel.order}: {teamName(duel.team_a)} — {teamName(duel.team_b)}
          </h4>
          <ul>
            {duel.pairs.map((pair) => (
              <li key={pair.k}>
                Пара {pair.k}: {pair.a} и {pair.b}
              </li>
            ))}
          </ul>
        </section>
      ))}
      <h3>Резерв</h3>
      <p>С ОВЗ: {protocol.reserve_ovz.join(', ') || '—'}</p>
      <p>Без ОВЗ: {protocol.reserve_general.join(', ') || '—'}</p>
    </article>
  )
}
