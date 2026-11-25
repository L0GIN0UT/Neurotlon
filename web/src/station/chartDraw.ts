// Отрисовка графика сигналов на canvas. Чистая по входу: хранилище, размеры, цвета, время.
import {
  burstsFor,
  GRID,
  inWindow,
  splitValid,
  timeToX,
  trackLabel,
  valueToY,
  WINDOW_MS,
} from './calibration.ts'
import type { SignalStore } from './calibration.ts'
import * as t from './texts.ts'

export interface ChartColors {
  text: string
  muted: string
  grid: string
  invalid: string
  burst: string
  /** Цвет линии по имени сигнала. */
  lines: Record<string, string>
  fallback: string
}

export interface ChartGeometry {
  /** Размер в CSS-пикселях. */
  width: number
  height: number
  /** Физических пикселей в CSS-пикселе: линии выравниваются по ним, чтобы были чёткими. */
  dpr: number
  /** Пикселей в 1rem: шрифты и отступы растут вместе с окном станции. */
  rem: number
}

const FONT = "'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif"

/** Координата линии шириной в один физический пиксель: по центру пикселя, без размытия. */
export const crisp = (v: number, dpr: number): number => (Math.round(v * dpr) + 0.5) / dpr

function drawLane(
  ctx: CanvasRenderingContext2D,
  store: SignalStore,
  signal: string,
  end: number,
  box: { left: number; top: number; width: number; height: number },
  g: ChartGeometry,
  colors: ChartColors,
): void {
  const { left, top, width, height } = box
  const hair = 1 / g.dpr

  // сетка и подписи шкалы
  ctx.font = `600 ${0.95 * g.rem}px ${FONT}`
  ctx.textBaseline = 'middle'
  ctx.textAlign = 'right'
  ctx.lineWidth = hair
  for (const level of GRID) {
    const y = crisp(valueToY(level, top, height), g.dpr)
    const edge = level === 0 || level === 1
    ctx.strokeStyle = edge ? colors.muted : colors.grid
    ctx.globalAlpha = edge ? 0.55 : 1
    ctx.beginPath()
    ctx.moveTo(left, y)
    ctx.lineTo(left + width, y)
    ctx.stroke()
    ctx.globalAlpha = 1
    ctx.fillStyle = colors.muted
    ctx.fillText(level === 0 || level === 1 ? String(level) : String(level).replace('.', ','), left - 0.6 * g.rem, y)
  }

  const samples = inWindow(store.samples(signal), end)
  const color = colors.lines[signal] ?? colors.fallback

  ctx.save()
  ctx.beginPath()
  ctx.rect(left, top - 2, width, height + 4)
  ctx.clip()

  const segments = splitValid(samples)
  for (const segment of segments) {
    const first = samples[segment.start]
    const last = samples[segment.end]
    if (!first || !last) continue
    if (!segment.ok) {
      const after = samples[segment.end + 1]
      const x0 = timeToX(first.t, end, left, width)
      const x1 = timeToX(after ? after.t : last.t, end, left, width)
      drawInvalid(ctx, x0, top, Math.max(x1 - x0, 2), height, segment.reason ?? '', g, colors)
    }
  }
  for (const segment of segments) {
    if (!segment.ok) continue
    ctx.strokeStyle = color
    ctx.fillStyle = color
    ctx.lineWidth = Math.max(2, 0.28 * g.rem)
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    ctx.beginPath()
    for (let i = segment.start; i <= segment.end; i += 1) {
      const s = samples[i]
      if (!s) continue
      const x = timeToX(s.t, end, left, width)
      const y = valueToY(s.v, top, height)
      if (i === segment.start) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
    if (segment.start === segment.end) {
      const s = samples[segment.start]
      if (s) {
        ctx.beginPath()
        ctx.arc(timeToX(s.t, end, left, width), valueToY(s.v, top, height), ctx.lineWidth * 0.8, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }
  ctx.restore()

  // метки burst: вертикальная линия на всю дорожку и «флажок» сверху
  for (const burst of burstsFor(store.bursts(), signal, end)) {
    const x = crisp(timeToX(burst.t, end, left, width), g.dpr)
    ctx.strokeStyle = colors.burst
    ctx.lineWidth = Math.max(2, 0.2 * g.rem)
    ctx.beginPath()
    ctx.moveTo(x, top)
    ctx.lineTo(x, top + height)
    ctx.stroke()
    ctx.fillStyle = colors.burst
    const flag = 0.55 * g.rem
    ctx.beginPath()
    ctx.moveTo(x - flag, top - 1)
    ctx.lineTo(x + flag, top - 1)
    ctx.lineTo(x, top + flag * 1.1)
    ctx.closePath()
    ctx.fill()
  }
}

/** Серый участок: штриховка и подпись причины, если она помещается. */
function drawInvalid(
  ctx: CanvasRenderingContext2D,
  x: number,
  top: number,
  width: number,
  height: number,
  reason: string,
  g: ChartGeometry,
  colors: ChartColors,
): void {
  ctx.save()
  ctx.beginPath()
  ctx.rect(x, top, width, height)
  ctx.clip()
  ctx.fillStyle = colors.invalid
  ctx.globalAlpha = 0.16
  ctx.fillRect(x, top, width, height)
  ctx.globalAlpha = 0.5
  ctx.strokeStyle = colors.invalid
  ctx.lineWidth = 1.5
  const step = 0.9 * g.rem
  ctx.beginPath()
  for (let dx = -height; dx < width; dx += step) {
    ctx.moveTo(x + dx, top + height)
    ctx.lineTo(x + dx + height, top)
  }
  ctx.stroke()
  ctx.restore()

  ctx.font = `700 ${1.05 * g.rem}px ${FONT}`
  const label = reason
  const need = ctx.measureText(label).width + 0.8 * g.rem
  if (label && width >= need) {
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = colors.text
    ctx.globalAlpha = 0.9
    ctx.fillText(label, x + width / 2, top + height / 2)
    ctx.globalAlpha = 1
  }
}

/** Рисует все дорожки и ось времени. Вызывается в каждом кадре `requestAnimationFrame`. */
export function drawChart(
  ctx: CanvasRenderingContext2D,
  store: SignalStore,
  tracks: readonly string[],
  now: number,
  g: ChartGeometry,
  colors: ChartColors,
): void {
  ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0)
  ctx.clearRect(0, 0, g.width, g.height)

  const left = 3.6 * g.rem
  const right = 1.2 * g.rem
  const plotWidth = Math.max(10, g.width - left - right)
  const header = 1.9 * g.rem
  const axis = 1.9 * g.rem
  const gap = 0.6 * g.rem
  const count = Math.max(1, tracks.length)
  const laneHeight = Math.max(10, (g.height - axis - count * header - (count - 1) * gap) / count)

  const end = store.windowEnd(now)
  if (end === null) {
    ctx.fillStyle = colors.muted
    ctx.font = `600 ${1.5 * g.rem}px ${FONT}`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(t.CALIB.noSignal, g.width / 2, g.height / 2)
    return
  }

  tracks.forEach((signal, i) => {
    const top = i * (header + laneHeight + gap) + header
    ctx.fillStyle = colors.lines[signal] ?? colors.fallback
    ctx.font = `700 ${1.15 * g.rem}px ${FONT}`
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(trackLabel(signal), left, top - header / 2 - 0.1 * g.rem)
    drawLane(ctx, store, signal, end, { left, top, width: plotWidth, height: laneHeight }, g, colors)
  })

  // ось времени: «−10 с … 0»
  const axisY = g.height - axis / 2 + 0.2 * g.rem
  ctx.fillStyle = colors.muted
  ctx.font = `600 ${0.95 * g.rem}px ${FONT}`
  ctx.textBaseline = 'middle'
  for (const sec of [10, 5, 0]) {
    const x = timeToX(end - sec * 1000, end, left, plotWidth, WINDOW_MS)
    ctx.textAlign = sec === 10 ? 'left' : sec === 0 ? 'right' : 'center'
    ctx.fillText(sec === 0 ? t.CALIB.axisNow : t.CALIB.axisAgo(sec), x, axisY)
  }
}
