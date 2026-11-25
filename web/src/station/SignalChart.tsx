import { useEffect, useRef } from 'react'
import type { SignalStore } from './calibration.ts'
import { drawChart } from './chartDraw.ts'
import type { ChartColors } from './chartDraw.ts'

const LINE_VARS: Record<string, string> = {
  eeg: '--good',
  emg: '--accent',
  emg_left: '--accent',
  emg_right: '--good',
}

/** Цвета берём из токенов станции, чтобы график менялся вместе с темой и цветом дисциплины. */
function readColors(element: Element): ChartColors {
  const style = getComputedStyle(element)
  const token = (name: string, fallback: string): string => style.getPropertyValue(name).trim() || fallback
  const lines: Record<string, string> = {}
  for (const [signal, name] of Object.entries(LINE_VARS)) lines[signal] = token(name, '#5b8cff')
  return {
    text: token('--text', '#f1f5ff'),
    muted: token('--muted', '#9fb0d6'),
    grid: 'rgb(255 255 255 / 10%)',
    invalid: '#9aa5bf',
    burst: token('--warn', '#f2b705'),
    lines,
    fallback: token('--accent', '#5b8cff'),
  }
}

/**
 * График сигналов за последние 10 с: canvas и `requestAnimationFrame`. Данные берутся прямо из буфера,
 * поэтому React не перерисовывается на каждое значение. Размер следует за контейнером и `devicePixelRatio`.
 */
export function SignalChart({
  store,
  tracks,
  label,
}: {
  store: SignalStore
  tracks: readonly string[]
  label: string
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const trackKey = tracks.join(',')

  useEffect(() => {
    const canvas = canvasRef.current
    const box = canvas?.parentElement
    const ctx = canvas?.getContext('2d') ?? null
    if (!canvas || !box || !ctx) return

    const names = trackKey ? trackKey.split(',') : []
    let frame = 0
    let width = 0
    let height = 0
    let dpr = window.devicePixelRatio || 1
    let colors = readColors(canvas)
    let rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16

    const resize = () => {
      const rect = box.getBoundingClientRect()
      dpr = window.devicePixelRatio || 1
      width = Math.max(1, Math.round(rect.width))
      height = Math.max(1, Math.round(rect.height))
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
      colors = readColors(canvas)
    }
    resize()

    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null
    observer?.observe(box)
    window.addEventListener('resize', resize)

    const tick = () => {
      drawChart(ctx, store, names, performance.now(), { width, height, dpr, rem }, colors)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener('resize', resize)
    }
  }, [store, trackKey])

  return (
    <div className="signal-chart">
      <canvas ref={canvasRef} role="img" aria-label={label} />
    </div>
  )
}
