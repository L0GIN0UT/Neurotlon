import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import { TEAM_PALETTE, parseHex } from './colors.ts'
import './ColorPicker.css'

/** Минимальный отступ окошка от края экрана и число колонок палитры (как в CSS). */
const GAP = 8
const COLUMNS = 7

/** Кружок с цветом и всплывающее окошко: палитра и поле «свой цвет». Без системного окна выбора. */
export function ColorPicker({
  value,
  label,
  onChange,
  palette = TEAM_PALETTE,
}: {
  value: string
  label: string
  onChange: (hex: string) => void
  palette?: readonly string[]
}) {
  const [open, setOpen] = useState(false)
  const [custom, setCustom] = useState('')
  const [pos, setPos] = useState<CSSProperties>({ visibility: 'hidden' })
  const root = useRef<HTMLSpanElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const pop = useRef<HTMLDivElement>(null)
  const swatches = useRef<(HTMLButtonElement | null)[]>([])
  const titleId = useId()
  const current = value.toLowerCase()
  const customHex = parseHex(custom)
  const customBad = custom.trim() !== '' && customHex === null

  function close(restoreFocus: boolean) {
    setOpen(false)
    if (restoreFocus) button.current?.focus()
  }

  function pick(hex: string) {
    onChange(hex.toLowerCase())
    close(true)
  }

  // Окошко fixed: его не обрезают карточки; на узком экране прижимается к границам.
  useLayoutEffect(() => {
    if (!open || !button.current || !pop.current) return
    const anchor = button.current.getBoundingClientRect()
    const width = pop.current.offsetWidth
    const height = pop.current.offsetHeight
    const left = Math.max(GAP, Math.min(anchor.left, window.innerWidth - width - GAP))
    const below = anchor.bottom + 6
    const top =
      below + height + GAP <= window.innerHeight
        ? below
        : Math.max(GAP, anchor.top - 6 - height)
    setPos({ left, top })
  }, [open])

  useEffect(() => {
    if (!open) return
    const start = Math.max(0, palette.findIndex((c) => c.toLowerCase() === current))
    swatches.current[start]?.focus()
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node) && !pop.current?.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const dismiss = () => setOpen(false)
    document.addEventListener('mousedown', onDown)
    window.addEventListener('resize', dismiss)
    window.addEventListener('scroll', dismiss, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('resize', dismiss)
      window.removeEventListener('scroll', dismiss, true)
    }
  }, [open, palette, current])

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') {
      e.stopPropagation()
      close(true)
      return
    }
    const index = swatches.current.findIndex((s) => s === document.activeElement)
    if (index < 0) return
    const moves: Record<string, number> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: COLUMNS,
      ArrowUp: -COLUMNS,
    }
    const delta = moves[e.key]
    if (delta === undefined) return
    e.preventDefault()
    const next = index + delta
    if (next >= 0 && next < palette.length) swatches.current[next]?.focus()
  }

  return (
    <span className="cp" ref={root}>
      <button
        type="button"
        ref={button}
        className="cp-button"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        style={{ background: current }}
        onClick={() => {
          setPos({ visibility: 'hidden' })
          setCustom('')
          setOpen((o) => !o)
        }}
      />
      {open && (
        <div
          ref={pop}
          className="cp-pop"
          role="dialog"
          aria-labelledby={titleId}
          style={pos}
          onKeyDown={onKeyDown}
        >
          <span id={titleId} className="cp-title">
            Выберите цвет
          </span>
          <div className="cp-grid">
            {palette.map((hex, i) => {
              const selected = hex.toLowerCase() === current
              return (
                <button
                  key={hex}
                  type="button"
                  ref={(el) => {
                    swatches.current[i] = el
                  }}
                  className="cp-swatch"
                  aria-label={hex}
                  aria-pressed={selected}
                  style={{ background: hex }}
                  onClick={() => pick(hex)}
                >
                  {selected && (
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M5 12.5l4.5 4.5L19 7.5" />
                    </svg>
                  )}
                </button>
              )
            })}
          </div>
          <form
            className="cp-custom"
            onSubmit={(e) => {
              e.preventDefault()
              if (customHex) pick(customHex)
            }}
          >
            <span
              className="cp-preview"
              style={{ background: customHex ?? 'transparent' }}
              aria-hidden="true"
            />
            <input
              className="cp-input"
              aria-label="Свой цвет (HEX)"
              aria-invalid={customBad}
              placeholder="#RRGGBB"
              maxLength={7}
              spellCheck={false}
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
            />
            <button type="submit" className="cp-apply" disabled={!customHex}>
              Выбрать
            </button>
          </form>
          {customBad && <span className="cp-error">Формат: #RRGGBB</span>}
        </div>
      )}
    </span>
  )
}
