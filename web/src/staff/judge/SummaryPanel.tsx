import type { StaffApi } from '../api.ts'
import { ExportLink } from '../ExportLink.tsx'
import { useLoader } from '../hooks.ts'
import { ErrorText } from '../ui.tsx'
import { LockPanel } from './LockPanel.tsx'
import './Summary.css'

export type SummaryTarget = 'conflicts' | 'corrections'

interface Props {
  api: StaffApi
  canForce: boolean
  onNavigate: (tab: SummaryTarget) => void
}

interface Totals {
  total: number
  confirmed: number
  locked: number
  conflicts: number
  openCorrections: number
}

async function loadTotals(api: StaffApi): Promise<Totals> {
  const [results, conflicts, corrections] = await Promise.all([
    api.allResults(),
    api.conflicts(),
    api.corrections('open'),
  ])
  const active = results.filter((r) => !r.voided)
  return {
    total: active.length,
    confirmed: active.filter((r) => r.status === 'confirmed').length,
    locked: active.filter((r) => r.status === 'locked').length,
    conflicts: conflicts.length,
    openCorrections: corrections.length,
  }
}

/** Невыполненные пункты чек-листа: показываются и в окне подтверждения фиксации. */
function unreadyItems(t: Totals): string[] {
  const items: string[] = []
  if (t.conflicts > 0) items.push(`Неразрешённых конфликтов: ${t.conflicts}`)
  if (t.openCorrections > 0) items.push(`Открытых запросов на исправление: ${t.openCorrections}`)
  if (t.confirmed === 0) items.push('Нет подтверждённых результатов для фиксации')
  return items
}

function CheckIcon({ ok }: { ok: boolean }) {
  return (
    <svg
      className="mark"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={ok ? 'Выполнено' : 'Требует внимания'}
    >
      {ok ? (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="m8 12.5 3 3 5-6" />
        </>
      ) : (
        <>
          <path d="M12 3 2.5 20h19L12 3Z" />
          <path d="M12 10v4M12 17.2v.01" />
        </>
      )}
    </svg>
  )
}

interface CheckProps {
  ok: boolean
  text: string
  link?: { label: string; onClick: () => void }
}

function CheckItem({ ok, text, link }: CheckProps) {
  return (
    <li className={ok ? 'ok' : 'attention'}>
      <CheckIcon ok={ok} />
      <span className="text">{text}</span>
      {!ok && link && (
        <button type="button" className="link" onClick={link.onClick}>
          {link.label}
        </button>
      )}
    </li>
  )
}

interface TileProps {
  label: string
  value: number | undefined
  tone?: 'good' | 'warn' | 'bad'
}

function Tile({ label, value, tone }: TileProps) {
  return (
    <div className={`summary-tile ${tone ?? ''}`}>
      <dt>{label}</dt>
      <dd>{value ?? '…'}</dd>
    </div>
  )
}

export function SummaryPanel({ api, canForce, onNavigate }: Props) {
  const loader = useLoader(() => loadTotals(api))
  const totals = loader.data

  return (
    <>
      <ErrorText error={loader.error} />
      <dl className="summary-tiles" aria-label="Сводка">
        <Tile label="Всего результатов" value={totals?.total} />
        <Tile label="Подтверждено" value={totals?.confirmed} tone="good" />
        <Tile label="Зафиксировано" value={totals?.locked} />
        <Tile
          label="Конфликтов"
          value={totals?.conflicts}
          tone={totals && totals.conflicts > 0 ? 'bad' : undefined}
        />
        <Tile
          label="Открытых запросов на исправление"
          value={totals?.openCorrections}
          tone={totals && totals.openCorrections > 0 ? 'warn' : undefined}
        />
      </dl>

      <section className="card stack">
        <h2>Готовность к фиксации</h2>
        {totals ? (
          <ul className="summary-check">
            <CheckItem
              ok={totals.conflicts === 0}
              text={
                totals.conflicts === 0
                  ? 'Нет конфликтов результатов'
                  : `Есть конфликты результатов: ${totals.conflicts}`
              }
              link={{ label: 'Перейти к конфликтам', onClick: () => onNavigate('conflicts') }}
            />
            <CheckItem
              ok={totals.openCorrections === 0}
              text={
                totals.openCorrections === 0
                  ? 'Нет открытых запросов на исправление'
                  : `Есть открытые запросы на исправление: ${totals.openCorrections}`
              }
              link={{ label: 'Перейти к запросам', onClick: () => onNavigate('corrections') }}
            />
            <CheckItem
              ok={totals.confirmed > 0}
              text={`Есть что фиксировать (подтверждённых результатов: ${totals.confirmed})`}
            />
          </ul>
        ) : (
          <p className="hint">{loader.error ? 'Не удалось проверить готовность.' : 'Проверяем…'}</p>
        )}
        <p className="hint">
          Зафиксировать можно и при невыполненных пунктах: решение за судьёй, перед фиксацией
          будет предупреждение.
        </p>
      </section>

      <div className="summary-actions">
        <LockPanel
          api={api}
          canForce={canForce}
          warnings={totals ? unreadyItems(totals) : []}
          onLocked={loader.reload}
        />
        <ExportLink />
      </div>
    </>
  )
}
