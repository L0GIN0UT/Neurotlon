import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { errorText } from '../shared/messages.ts'
import { PageHead, StaffShell } from '../staff/StaffShell.tsx'
import type { QrMatrix, StaffApi } from '../staff/api.ts'
import { useLoader } from '../staff/hooks.ts'
import { Badge } from './Badge.tsx'
import { parseCodes } from './codes.ts'
import './badges.css'

type Mode = 'press' | 'a4'
type Scope = 'all' | 'selected'

const MODES: { id: Mode; label: string }[] = [
  { id: 'press', label: 'Для типографии (95×135 мм, один бейдж на страницу)' },
  { id: 'a4', label: 'На A4 по 4 (с метками реза)' },
]

/** Правило страницы зависит от режима: два разных `@page` в одном документе не смешиваем. */
const PAGE_RULES: Record<Mode, string> = {
  press: '@page { size: 95mm 135mm; margin: 0 }',
  a4: '@page { size: A4; margin: 5mm }',
}

const BADGE_W_MM = 95
const BADGE_H_MM = 135
/** Поле для меток реза вокруг бейджа в режиме A4. */
const MARK_MM = 2.5
const A4_PER_SHEET = 4
const MM_PX = 96 / 25.4

/** Масштаб предпросмотра: натуральный размер, а на узком окне уменьшается до ширины окна. */
function usePreviewScale(widthMm: number): number {
  const [scale, setScale] = useState(1)
  useEffect(() => {
    function update() {
      const available = window.innerWidth - 64
      const next = available > 0 ? Math.min(1, available / (widthMm * MM_PX)) : 1
      setScale(Number.isFinite(next) && next > 0 ? next : 1)
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [widthMm])
  return scale
}

/** Обёртка с размером в мм: на экране масштабируется, в печати масштаб сбрасывается (см. CSS). */
function Scaled({ w, h, scale, children }: { w: number; h: number; scale: number; children: ReactNode }) {
  const style = { '--w': `${w}mm`, '--h': `${h}mm`, '--s': scale } as CSSProperties
  return (
    <div className="scaled" style={style}>
      <div className="scaled-inner">{children}</div>
    </div>
  )
}

function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size))
  return out
}

function Sheets({ mode, badges }: { mode: Mode; badges: QrMatrix[] }) {
  const sheetW = 2 * (BADGE_W_MM + 2 * MARK_MM)
  const sheetH = 2 * (BADGE_H_MM + 2 * MARK_MM)
  const scale = usePreviewScale(mode === 'press' ? BADGE_W_MM : sheetW)
  if (mode === 'press') {
    return (
      <>
        {badges.map((b) => (
          <div key={b.code} className="page">
            <Scaled w={BADGE_W_MM} h={BADGE_H_MM} scale={scale}>
              <Badge matrix={b} />
            </Scaled>
          </div>
        ))}
      </>
    )
  }
  return (
    <>
      {chunk(badges, A4_PER_SHEET).map((group) => (
        <div key={group[0]?.code} className="page">
          <Scaled w={sheetW} h={sheetH} scale={scale}>
            <div className="a4-sheet">
              {group.map((b) => (
                <div key={b.code} className="cut-cell">
                  <Badge matrix={b} />
                </div>
              ))}
            </div>
          </Scaled>
        </div>
      ))}
    </>
  )
}

function BadgesPage({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.participants())
  const qr = useLoader(() => api.participantQr())
  const [mode, setMode] = useState<Mode>('press')
  const [sponsors, setSponsors] = useState(true)
  const initial = useMemo(() => parseCodes(window.location.search), [])
  const [scope, setScope] = useState<Scope>(initial.length > 0 ? 'selected' : 'all')
  const [picked, setPicked] = useState<Set<string>>(() => new Set(initial))

  const allCodes = useMemo(() => (list.data ?? []).map((p) => p.code), [list.data])
  const matrices = qr.data
  const shown = useMemo(() => {
    const byCode = new Map((matrices ?? []).map((m) => [m.code, m]))
    const codes = scope === 'all' ? allCodes : allCodes.filter((c) => picked.has(c))
    return codes.flatMap((c) => byCode.get(c) ?? [])
  }, [matrices, allCodes, picked, scope])

  function toggle(code: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }

  const error = list.error ?? qr.error
  return (
    <div className={`badges-root mode-${mode}${sponsors ? '' : ' sponsors-off'}`}>
      <style>{PAGE_RULES[mode]}</style>
      <div className="no-print stack">
        <PageHead
          title="Бейджи"
          hint="Бейдж без команды и имени: место под фото, код, QR, таблица результатов и места для партнёров."
        />
        <div className="card stack">
          <div className="row">
            <a href="/admin">← Участники</a>
            <div className="row" role="group" aria-label="Режим печати">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className={mode === m.id ? 'primary' : ''}
                  aria-pressed={mode === m.id}
                  onClick={() => setMode(m.id)}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
          <div className="row" role="group" aria-label="Кого печатать">
            <label>
              <input type="radio" name="scope" checked={scope === 'all'} onChange={() => setScope('all')} /> Все
            </label>
            <label>
              <input
                type="radio"
                name="scope"
                checked={scope === 'selected'}
                onChange={() => setScope('selected')}
              />{' '}
              Отмеченные
            </label>
            <label>
              <input type="checkbox" checked={sponsors} onChange={(e) => setSponsors(e.target.checked)} /> Показывать
              места под спонсоров
            </label>
            <button
              type="button"
              className="primary"
              disabled={shown.length === 0}
              onClick={() => window.print()}
            >
              Печать / Сохранить в PDF
            </button>
            <span className="hint">К печати: {shown.length}</span>
          </div>
          {scope === 'selected' && (
            <div className="row code-picker" role="group" aria-label="Коды участников">
              {allCodes.map((code) => (
                <label key={code}>
                  <input type="checkbox" checked={picked.has(code)} onChange={() => toggle(code)} /> {code}
                </label>
              ))}
            </div>
          )}
          <p className="hint">
            В окне печати выберите принтер «Сохранить как PDF», поля «Нет», включите «Фоновая графика».
          </p>
          {error != null && (
            <p role="alert" className="error">
              {errorText(error)}
            </p>
          )}
        </div>
      </div>
      <div className="badge-list">
        <Sheets mode={mode} badges={shown} />
      </div>
    </div>
  )
}

export function BadgesApp({ fetchFn }: { fetchFn?: typeof fetch }) {
  return (
    <StaffShell title="Бейджи" allow={['admin', 'superuser']} fetchFn={fetchFn}>
      {({ api }) => <BadgesPage api={api} />}
    </StaffShell>
  )
}
