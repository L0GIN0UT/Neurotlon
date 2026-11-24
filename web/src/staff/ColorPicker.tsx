import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import { TEAM_PALETTE, parseHex } from './colors.ts'
import './ColorPicker.css'

/** Минимальный отступ окошка от края экрана и число колонок палитры (как в CSS). */
const GAP = 8
const COLUMNS = 7
/** До расчёта позиции окошко прозрачно, но не `visibility: hidden`: такой элемент не берёт фокус. */
const HIDDEN: CSSProperties = { left: 0, top: 0, opacity: 0, pointerEvents: 'none' }

/** Кружок с цветом и всплывающее окошко: палитра и поле «свой цвет». Без системного окна выбора. */
export function ColorPicker({
  value,
  label,
  onChange,
  disabled = false,
  palette = TEAM_PALETTE,
}: {
  value: string
  label: string
  onChange: (hex: string) => void
  /** Идёт сохранение: выбор временно не принимается. */
  disabled?: boolean
  palette?: readonly string[]
}) {
  const [open, setOpen] = useState(false)
  const [custom, setCustom] = useState('')
  const [pos, setPos] = useState<CSSProperties>(HIDDEN)
  const [placed, setPlaced] = useState(false)
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
    // Пока предыдущий выбор сохраняется, новый не принимается: иначе он бы потерялся.
    if (disabled) return
    onChange(hex.toLowerCase())
    close(true)
  }

  // Окошко fixed: его не обрезают карточки; на узком экране прижимается к границам.
  const place = useCallback(() => {
    if (!button.current || !pop.current) return
    const anchor = button.current.getBoundingClientRect()
    const width = pop.current.offsetWidth
    const height = pop.current.offsetHeight
    const left = Math.max(GAP, Math.min(anchor.left, window.innerWidth - width - GAP))
    const below = anchor.bottom + 6
    const top =
      below + height + GAP <= window.innerHeight ? below : Math.max(GAP, anchor.top - 6 - height)
    setPos({ left, top })
    setPlaced(true)
  }, [])

  useLayoutEffect(() => {
    if (open) place()
  }, [open, place])

  // Фокус на палитру только когда окошко стоит на месте и видимо: скрытый элемент фокус не берёт.
  useEffect(() => {
    if (!open || !placed) return
    // Фокус — на отмеченный цвет; смена цвета при открытом окошке фокус не двигает.
    const selected = swatches.current.findIndex((s) => s?.getAttribute('aria-pressed') === 'true')
    swatches.current[Math.max(0, selected)]?.focus()
  }, [open, placed])

  useEffect(() => {
    if (!open) return
    let width = window.innerWidth
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') close(true)
    }
    // Ширина не менялась (экранная клавиатура планшета): окошко остаётся, позиция пересчитывается.
    const onResize = () => {
      if (window.innerWidth !== width) setOpen(false)
      else place()
      width = window.innerWidth
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', onResize)
    window.addEventListener('scroll', place, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, place])

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
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
        aria-disabled={disabled}
        style={{ background: current }}
        onClick={() => {
          if (disabled && !open) return
          setPos(HIDDEN)
          setPlaced(false)
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
          onBlur={(e) => {
            const next = e.relatedTarget
            if (next instanceof Node && !root.current?.contains(next)) setOpen(false)
          }}
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
                  aria-disabled={disabled}
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
