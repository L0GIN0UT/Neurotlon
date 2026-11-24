import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode, RefObject } from 'react'
import { errorText } from '../shared/messages.ts'
import { PageHead, StaffShell } from '../staff/StaffShell.tsx'
import { BADGES_URL, photoUrl } from '../staff/api.ts'
import type { Participant, QrMatrix, StaffApi } from '../staff/api.ts'
import { PhotoThumb } from '../staff/admin/PhotoThumb.tsx'
import '../staff/admin/PhotoDialog.css'
import { useLoader } from '../staff/hooks.ts'
import { PrinterIcon } from '../staff/ui.tsx'
import { Badge } from './Badge.tsx'
import type { BadgePhoto, PhotoReport, PhotoState } from './Badge.tsx'
import { parseCodes } from './codes.ts'
import './badges.css'

type Mode = 'press' | 'a4' | 'a3'

/** Листы с метками реза: сколько бейджей в строке и в столбце. */
const SHEETS: Record<'a4' | 'a3', { cols: number; rows: number }> = {
  a4: { cols: 2, rows: 2 },
  a3: { cols: 4, rows: 2 },
}

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: 'a4', label: 'A4 по 4', hint: 'Лист A4, 2×2, метки реза' },
  { id: 'a3', label: 'A3 по 8', hint: 'Лист A3 альбомный, 4×2, метки реза' },
  { id: 'press', label: 'Для типографии 95×135', hint: 'Один бейдж на страницу' },
]

/** Правило страницы зависит от режима: два разных `@page` в одном документе не смешиваем. */
const PAGE_RULES: Record<Mode, string> = {
  press: '@page { size: 95mm 135mm; margin: 0 }',
  a4: '@page { size: A4; margin: 5mm }',
  a3: '@page { size: A3 landscape; margin: 5mm }',
}

const BADGE_W_MM = 95
const BADGE_H_MM = 135
/** Поле для меток реза вокруг бейджа в режиме A4. */
const MARK_MM = 2.5
const MM_PX = 96 / 25.4

/** Масштаб предпросмотра: натуральный размер, а в узкой колонке уменьшается до её ширины. */
function usePreviewScale(widthMm: number, host: RefObject<HTMLElement | null>): number {
  const [scale, setScale] = useState(1)
  useEffect(() => {
    const element = host.current
    function update() {
      const available = (element?.clientWidth ?? 0) - 8
      const next = available > 0 ? Math.min(1, available / (widthMm * MM_PX)) : 1
      setScale(Number.isFinite(next) && next > 0 ? next : 1)
    }
    update()
    window.addEventListener('resize', update)
    const observer = typeof ResizeObserver === 'function' && element ? new ResizeObserver(update) : null
    if (observer && element) observer.observe(element)
    return () => {
      window.removeEventListener('resize', update)
      observer?.disconnect()
    }
  }, [widthMm, host])
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

/** Всё, что нужно одному бейджу. */
interface Entry {
  matrix: QrMatrix
  name: string | null
  photo: BadgePhoto | null
}

function Sheets({
  mode,
  entries,
  sponsors,
  onPhoto,
  host,
}: {
  mode: Mode
  entries: Entry[]
  sponsors: boolean
  onPhoto: PhotoReport
  host: RefObject<HTMLElement | null>
}) {
  const { cols, rows } = SHEETS[mode === 'a3' ? 'a3' : 'a4']
  const sheetW = cols * (BADGE_W_MM + 2 * MARK_MM)
  const sheetH = rows * (BADGE_H_MM + 2 * MARK_MM)
  const scale = usePreviewScale(mode === 'press' ? BADGE_W_MM : sheetW, host)
  const badge = (e: Entry) => <Badge matrix={e.matrix} name={e.name} photo={e.photo} sponsors={sponsors} onPhoto={onPhoto} />
  if (mode === 'press') {
    return (
      <>
        {entries.map((e) => (
          <div key={e.matrix.code} className="page">
            <Scaled w={BADGE_W_MM} h={BADGE_H_MM} scale={scale}>
              {badge(e)}
            </Scaled>
          </div>
        ))}
      </>
    )
  }
  return (
    <>
      {chunk(entries, cols * rows).map((group) => (
        <div key={group[0]?.matrix.code} className="page">
          <Scaled w={sheetW} h={sheetH} scale={scale}>
            <div className="a4-sheet" style={{ '--cols': cols, '--rows': rows } as CSSProperties}>
              {group.map((e) => (
                <div key={e.matrix.code} className="cut-cell">
                  {badge(e)}
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
  const [mode, setMode] = useState<Mode>('a4')
  const [sponsors, setSponsors] = useState(true)
  const [search, setSearch] = useState('')
  const initial = useMemo(() => parseCodes(window.location.search), [])
  // null: выбор не менялся, печатаются все (или коды из ?codes=)
  const [picked, setPicked] = useState<Set<string> | null>(null)
  const host = useRef<HTMLDivElement>(null)

  const people: Participant[] = useMemo(() => list.data ?? [], [list.data])
  const allCodes = useMemo(() => people.map((p) => p.code), [people])
  const selected = useMemo(
    () => picked ?? (initial.length > 0 ? new Set(initial) : new Set(allCodes)),
    [picked, initial, allCodes],
  )
  const byCode = useMemo(() => new Map(people.map((p) => [p.code, p])), [people])

  const printable = useMemo(() => {
    const matrices = new Map((qr.data ?? []).map((m) => [m.code, m]))
    return allCodes.filter((c) => selected.has(c)).flatMap((c) => matrices.get(c) ?? [])
  }, [qr.data, allCodes, selected])

  const urls = useMemo(
    () =>
      printable.flatMap((m) => {
        const person = byCode.get(m.code)
        return person?.has_photo ? [photoUrl(m.code, person.photo_version)] : []
      }),
    [printable, byCode],
  )
  // Исход загрузки каждого настоящего <img> бейджа; загруженная картинка потом не «портится» ошибкой.
  const [photoStates, setPhotoStates] = useState<ReadonlyMap<string, PhotoState>>(() => new Map())
  const reportPhoto = useCallback<PhotoReport>((url, ok) => {
    setPhotoStates((prev) => {
      const current = prev.get(url)
      if (current === 'ok' || (!ok && current === 'error')) return prev
      return new Map(prev).set(url, ok ? 'ok' : 'error')
    })
  }, [])
  const pending = urls.filter((url) => !photoStates.has(url)).length
  const entries: Entry[] = printable.map((matrix) => {
    const person = byCode.get(matrix.code)
    const url = person?.has_photo ? photoUrl(matrix.code, person.photo_version) : null
    return {
      matrix,
      name: person?.display_name ?? null,
      photo: url === null ? null : { url, state: photoStates.get(url) ?? 'pending' },
    }
  })

  function toggle(code: string) {
    const next = new Set(selected)
    if (next.has(code)) next.delete(code)
    else next.add(code)
    setPicked(next)
  }

  const needle = search.trim().toLowerCase()
  const visible = people.filter(
    (p) => needle === '' || p.code.toLowerCase().includes(needle) || (p.display_name ?? '').toLowerCase().includes(needle),
  )
  const waiting = pending > 0
  const error = list.error ?? qr.error
  return (
    <div className={`badges-root mode-${mode}`}>
      <style>{PAGE_RULES[mode]}</style>
      <div className="no-print">
        <PageHead title="Печать бейджей" hint="Номер, имя на табло, фото, QR, таблица результатов и места под спонсоров." />
      </div>
      <div className="badges-layout">
        <aside className="no-print bp-panel card" aria-label="Параметры">
          <a className="button bp-back" href="/admin">
            ← Участники
          </a>
          <h2>Параметры</h2>

          <section className="bp-block" aria-labelledby="bp-size">
            <h3 id="bp-size">Размер листа</h3>
            <div className="bp-segment" role="group" aria-label="Размер листа">
              {MODES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={mode === item.id ? 'on' : ''}
                  aria-pressed={mode === item.id}
                  title={item.hint}
                  onClick={() => setMode(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </section>

          <section className="bp-block" aria-labelledby="bp-who">
            <h3 id="bp-who">Кого печатать</h3>
            <label className="field">
              Поиск
              <input
                type="search"
                value={search}
                placeholder="ID или имя на табло"
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <div className="bp-actions">
              <button type="button" className="small" onClick={() => setPicked(new Set(allCodes))}>
                Выбрать всех
              </button>
              <button
                type="button"
                className="small"
                onClick={() => setPicked(new Set(people.filter((p) => p.checked_in).map((p) => p.code)))}
              >
                Только пришедших
              </button>
              <button type="button" className="small ghost" onClick={() => setPicked(new Set())}>
                Снять выбор
              </button>
            </div>
            <p className="hint bp-count" role="status">
              Выбрано {selected.size} из {people.length}
            </p>
            <ul className="bp-people" role="group" aria-label="Коды участников">
              {visible.map((p) => (
                <li key={p.code}>
                  <label>
                    <input type="checkbox" checked={selected.has(p.code)} onChange={() => toggle(p.code)} />
                    <PhotoThumb person={p} />
                    <span className="bp-code">{p.code}</span>
                    <span className="bp-name">{p.display_name ?? ''}</span>
                  </label>
                </li>
              ))}
              {visible.length === 0 && <li className="hint">Никого не найдено.</li>}
            </ul>
          </section>

          <section className="bp-block" aria-labelledby="bp-look">
            <h3 id="bp-look">Оформление</h3>
            <label className="bp-switch">
              <input
                type="checkbox"
                role="switch"
                checked={sponsors}
                onChange={(e) => setSponsors(e.target.checked)}
              />
              <span className="bp-track" aria-hidden="true" />
              Места под спонсоров
            </label>
          </section>

          <div className="bp-print">
            <button
              type="button"
              className="primary bp-print-btn"
              disabled={printable.length === 0 || waiting}
              onClick={() => window.print()}
            >
              <PrinterIcon />
              Печать / Сохранить в PDF
            </button>
            {waiting ? (
              <p className="hint" role="status">
                Загрузка фото… ({urls.length - pending} из {urls.length})
              </p>
            ) : (
              <p className="hint">К печати: {printable.length}</p>
            )}
            <details className="bp-help">
              <summary>Как сохранить в PDF</summary>
              <p>В окне печати выберите принтер «Сохранить как PDF», поля «Нет», включите «Фоновая графика».</p>
              <p className="bp-small">
                <a href={BADGES_URL} target="_blank" rel="noopener noreferrer">
                  Простой PDF без фото
                </a>
              </p>
            </details>
          </div>
          {error != null && (
            <p role="alert" className="error">
              {errorText(error)}
            </p>
          )}
        </aside>
        <div className="badge-list" ref={host}>
          <Sheets mode={mode} entries={entries} sponsors={sponsors} onPhoto={reportPhoto} host={host} />
        </div>
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
