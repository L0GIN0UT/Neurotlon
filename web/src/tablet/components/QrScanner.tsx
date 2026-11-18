import { useEffect, useRef, useState } from 'react'
import { createQrReader } from '../qr.ts'

interface Props {
  onCode: (text: string) => void
  onClose: () => void
}

const SCAN_INTERVAL_MS = 250
const NO_CAMERA = 'Камера недоступна. Введите ID вручную.'

export function QrScanner({ onCode, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const onCodeRef = useRef(onCode)
  const [error, setError] = useState<string | null>(() =>
    typeof navigator !== 'undefined' && typeof navigator.mediaDevices?.getUserMedia === 'function'
      ? null : NO_CAMERA,
  )

  useEffect(() => {
    onCodeRef.current = onCode
  }, [onCode])

  useEffect(() => {
    if (typeof navigator.mediaDevices?.getUserMedia !== 'function') return
    let stream: MediaStream | null = null
    let timer: ReturnType<typeof setInterval> | undefined
    let stopped = false
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'environment' }, audio: false })
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
        const read = createQrReader(canvas)
        let busy = false
        timer = setInterval(() => {
          if (busy) return
          busy = true
          read(video)
            .then((text) => {
              if (text) onCodeRef.current(text)
            })
            .catch(() => undefined)
            .finally(() => {
              busy = false
            })
        }, SCAN_INTERVAL_MS)
      })
      .catch(() => {
        if (!stopped) setError(NO_CAMERA)
      })
    return () => {
      stopped = true
      clearInterval(timer)
      stream?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  return (
    <div className="scanner stack">
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : (
        <video ref={videoRef} playsInline muted aria-label="Камера" />
      )}
      <canvas ref={canvasRef} hidden />
      <button type="button" onClick={onClose}>
        Закрыть камеру
      </button>
    </div>
  )
}
