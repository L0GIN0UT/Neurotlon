import { useEffect, useRef, useState } from 'react'
import { createQrReader } from '../tablet/qr.ts'

const SCAN_INTERVAL_MS = 250
const REPEAT_WINDOW_MS = 3000 // один и тот же QR не принимается чаще раза в 3 с

export type CameraState = 'starting' | 'live' | 'unavailable'

/** Камера для чтения QR: видео в `videoRef`, найденные коды — в `onCode`. */
export function useQrCamera(onCode: (text: string) => void, enabled: boolean) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const onCodeRef = useRef(onCode)
  const [state, setState] = useState<CameraState>(() =>
    typeof navigator !== 'undefined' && typeof navigator.mediaDevices?.getUserMedia === 'function'
      ? 'starting'
      : 'unavailable',
  )

  useEffect(() => {
    onCodeRef.current = onCode
  }, [onCode])

  useEffect(() => {
    if (!enabled || typeof navigator.mediaDevices?.getUserMedia !== 'function') return
    let stream: MediaStream | null = null
    let timer: ReturnType<typeof setInterval> | undefined
    let stopped = false
    const seen = new Map<string, number>()
    canvasRef.current ??= document.createElement('canvas')
    navigator.mediaDevices
      .getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false })
      .then((media) => {
        const video = videoRef.current
        const canvas = canvasRef.current
        if (stopped || !video || !canvas) {
          media.getTracks().forEach((track) => track.stop())
          return
        }
        stream = media
        video.srcObject = media
        void video.play()
        setState('live')
        const read = createQrReader(canvas)
        let busy = false
        timer = setInterval(() => {
          if (busy) return
          busy = true
          read(video)
            .then((text) => {
              if (!text) return
              const now = Date.now()
              if (now - (seen.get(text) ?? 0) < REPEAT_WINDOW_MS) return
              seen.set(text, now)
              onCodeRef.current(text)
            })
            .catch(() => undefined)
            .finally(() => {
              busy = false
            })
        }, SCAN_INTERVAL_MS)
      })
      .catch(() => {
        if (!stopped) setState('unavailable')
      })
    return () => {
      stopped = true
      if (timer) clearInterval(timer)
      stream?.getTracks().forEach((track) => track.stop())
    }
  }, [enabled])

  return { videoRef, state }
}
