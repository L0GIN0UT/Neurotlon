import { useCallback, useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, RefObject } from 'react'
import { edgeScroll, slotAt, zoneAt } from './teamsLayout.ts'
import type { Area, Rect } from './teamsLayout.ts'

/** Пока указатель сдвинулся меньше, это обычный щелчок, а не перетаскивание. */
const START_DISTANCE = 5

export interface DropTarget {
  area: Area
  slot: number
}

export interface DragView {
  code: string
  /** Положение указателя в окне и его смещение внутри карточки при захвате. */
  x: number
  y: number
  offsetX: number
  offsetY: number
  width: number
  height: number
  target: DropTarget | null
}

interface Session {
  code: string
  pointerId: number
  startX: number
  startY: number
  offsetX: number
  offsetY: number
  width: number
  height: number
  x: number
  y: number
  active: boolean
}

interface Options {
  canStart: (code: string) => boolean
  onDrop: (code: string, target: DropTarget) => void
  /** Перетаскивание началось или закончилось: на это время фоновое обновление данных стоит. */
  onActiveChange: (active: boolean) => void
}

function rectOf(element: Element): Rect {
  const { left, right, top, bottom } = element.getBoundingClientRect()
  return { left, right, top, bottom }
}

/** Куда попадёт карточка: область под указателем и место среди её карточек (самой карточки не считаем). */
function targetAt(root: HTMLElement, code: string, x: number, y: number): DropTarget | null {
  const zones: Partial<Record<Area, Rect>> = {}
  for (const zone of root.querySelectorAll<HTMLElement>('[data-zone]')) {
    zones[zone.dataset.zone as Area] = rectOf(zone)
  }
  const area = zoneAt(x, y, zones)
  if (area === null) return null
  if (area === 'pool') return { area, slot: 0 }
  const mids = [...root.querySelectorAll<HTMLElement>(`[data-card][data-area="${area}"]`)]
    .filter((card) => card.dataset.card !== code)
    .map((card) => {
      const r = rectOf(card)
      return (r.top + r.bottom) / 2
    })
  return { area, slot: slotAt(y, mids) }
}

/**
 * Перетаскивание карточек указателем (мышь и палец): HTML5 drag-and-drop на планшетах не работает.
 * Начинается после небольшого сдвига; Escape и отпускание вне колонок отменяют.
 */
export function useCardDrag(root: RefObject<HTMLElement | null>, options: Options) {
  const [drag, setDrag] = useState<DragView | null>(null)
  const session = useRef<Session | null>(null)
  const frame = useRef<number | null>(null)
  const stopListening = useRef<(() => void) | null>(null)
  const latest = useRef(options)
  useEffect(() => {
    latest.current = options
  })

  const refresh = useCallback(() => {
    const s = session.current
    const element = root.current
    if (s === null || !s.active || element === null) return
    setDrag({
      code: s.code,
      x: s.x,
      y: s.y,
      offsetX: s.offsetX,
      offsetY: s.offsetY,
      width: s.width,
      height: s.height,
      target: targetAt(element, s.code, s.x, s.y),
    })
  }, [root])

  const finish = useCallback(
    (drop: boolean) => {
      const s = session.current
      session.current = null
      stopListening.current?.()
      stopListening.current = null
      if (frame.current !== null) cancelAnimationFrame(frame.current)
      frame.current = null
      if (s === null || !s.active) return
      const element = root.current
      const target = drop && element !== null ? targetAt(element, s.code, s.x, s.y) : null
      setDrag(null)
      latest.current.onActiveChange(false)
      if (target !== null) latest.current.onDrop(s.code, target)
    },
    [root],
  )

  /** Пока указатель у края окна, страница сама прокручивается и место вставки пересчитывается. */
  const autoScroll = useCallback(function tick() {
    frame.current = null
    const s = session.current
    if (s === null || !s.active) return
    const dy = edgeScroll(s.y, window.innerHeight)
    if (dy !== 0) {
      window.scrollBy(0, dy)
      refresh()
    }
    frame.current = requestAnimationFrame(tick)
  }, [refresh])

  const begin = useCallback(
    (event: ReactPointerEvent<HTMLElement>, code: string) => {
      if (session.current !== null || event.button > 0 || !latest.current.canStart(code)) return
      // Кнопки внутри карточки работают как обычно.
      const target = event.target as Element
      if (target.closest('button, input, a') !== null) return
      // Палец берёт карточку только за ручку (на ней touch-action: none); мышь и перо — за всю карточку.
      if (event.pointerType === 'touch' && target.closest('[data-grip]') === null) return
      const rect = event.currentTarget.getBoundingClientRect()
      session.current = {
        code,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        offsetX: event.clientX - rect.left,
        offsetY: event.clientY - rect.top,
        width: rect.width,
        height: rect.height,
        x: event.clientX,
        y: event.clientY,
        active: false,
      }

      const move = (e: PointerEvent) => {
        const s = session.current
        if (s === null || e.pointerId !== s.pointerId) return
        s.x = e.clientX
        s.y = e.clientY
        if (!s.active) {
          if (Math.hypot(s.x - s.startX, s.y - s.startY) < START_DISTANCE) return
          s.active = true
          latest.current.onActiveChange(true)
          frame.current = requestAnimationFrame(autoScroll)
        }
        refresh()
      }
      const up = (e: PointerEvent) => {
        if (e.pointerId === session.current?.pointerId) finish(true)
      }
      const cancel = (e: PointerEvent) => {
        if (e.pointerId === session.current?.pointerId) finish(false)
      }
      const key = (e: KeyboardEvent) => {
        if (e.key === 'Escape') finish(false)
      }
      window.addEventListener('pointermove', move)
      window.addEventListener('pointerup', up)
      window.addEventListener('pointercancel', cancel)
      window.addEventListener('keydown', key)
      stopListening.current = () => {
        window.removeEventListener('pointermove', move)
        window.removeEventListener('pointerup', up)
        window.removeEventListener('pointercancel', cancel)
        window.removeEventListener('keydown', key)
      }
    },
    [autoScroll, finish, refresh],
  )

  // Вкладку закрыли посреди перетаскивания: слушатели не остаются.
  useEffect(
    () => () => {
      stopListening.current?.()
      if (frame.current !== null) cancelAnimationFrame(frame.current)
      if (session.current?.active) latest.current.onActiveChange(false)
    },
    [],
  )

  return { drag, begin }
}
