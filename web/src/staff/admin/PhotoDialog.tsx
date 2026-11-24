import { useEffect, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import { photoErrorText } from '../../shared/messages.ts'
import type { Participant, StaffApi } from '../api.ts'
import { photoUrl } from '../api.ts'
import { useAction } from '../hooks.ts'
import { ConfirmDialog, Dialog, ErrorText } from '../ui.tsx'
import { clampCenter, cropRect, MAX_ZOOM, MIN_ZOOM } from './cropMath.ts'
import type { Point, Size } from './cropMath.ts'
import { PhotoPlaceholder } from './PhotoThumb.tsx'
import './PhotoDialog.css'

const OUT_WIDTH = 450
const OUT_HEIGHT = 600
const MAX_BYTES = 400 * 1024
/** Качество JPEG: от обычного к минимальному, пока файл не поместится в лимит. */
const QUALITIES = [0.85, 0.75, 0.65, 0.55, 0.5]

function canvasBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
}

/** JPEG не больше лимита сервера или null, если даже при минимальном качестве не помещается. */
async function encodeJpeg(canvas: HTMLCanvasElement): Promise<Blob | null> {
  for (const quality of QUALITIES) {
    const blob = await canvasBlob(canvas, quality)
    if (blob && blob.size <= MAX_BYTES) return blob
  }
  return null
}

function cameraProblem(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'Нет доступа к камере: разрешите её в настройках браузера'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'Камера не найдена'
  return 'Не удалось включить камеру'
}

interface Source {
  url: string
  /** Снимок с камеры: доступна кнопка «Переснять». */
  fromCamera: boolean
}

interface Props {
  api: StaffApi
  person: Participant
  onClose: () => void
  /** Фото сохранено или удалено: список нужно перезагрузить. */
  onSaved: () => void
}

export function PhotoDialog({ api, person, onClose, onSaved }: Props) {
  const action = useAction()
  const [source, setSource] = useState<Source | null>(null)
  const [size, setSize] = useState<Size | null>(null)
  const [zoom, setZoom] = useState(MIN_ZOOM)
  const [center, setCenter] = useState<Point>({ x: 0, y: 0 })
  const [camera, setCamera] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const drag = useRef<Point | null>(null)

  // Адрес объекта освобождается при смене снимка и при закрытии окна
  const sourceUrl = source?.url
  useEffect(() => {
    if (!sourceUrl) return
    return () => URL.revokeObjectURL(sourceUrl)
  }, [sourceUrl])

  // Поток камеры живёт только пока включён режим камеры; закрытие окна тоже его останавливает
  useEffect(() => {
    if (!camera) return
    let cancelled = false
    let stream: MediaStream | null = null
    const video = videoRef.current
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'user' }, audio: false })
      .then(
        (opened) => {
          if (cancelled) {
            opened.getTracks().forEach((track) => track.stop())
            return
          }
          stream = opened
          if (video) video.srcObject = opened
        },
        (error: unknown) => {
          if (cancelled) return
          setProblem(cameraProblem(error))
          setCamera(false)
        },
      )
    return () => {
      cancelled = true
      stream?.getTracks().forEach((track) => track.stop())
      if (video) video.srcObject = null
    }
  }, [camera])

  function openImage(url: string, fromCamera: boolean) {
    setSource({ url, fromCamera })
    setSize(null)
    setZoom(MIN_ZOOM)
    setProblem(null)
  }

  function chooseFile(file: File | undefined) {
    if (!file) return
    setCamera(false)
    openImage(URL.createObjectURL(file), false)
  }

  function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setProblem('Камера недоступна в этом браузере')
      return
    }
    setSource(null)
    setSize(null)
    setProblem(null)
    setCamera(true)
  }

  async function snapshot() {
    const video = videoRef.current
    if (!video || video.videoWidth === 0) {
      setProblem('Камера ещё не готова')
      return
    }
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')?.drawImage(video, 0, 0)
    const blob = await canvasBlob(canvas, 0.92)
    if (!blob) {
      setProblem('Не удалось сделать снимок')
      return
    }
    setCamera(false)
    openImage(URL.createObjectURL(blob), true)
  }

  function imageLoaded() {
    const img = imgRef.current
    if (!img) return
    setSize({ width: img.naturalWidth, height: img.naturalHeight })
    setCenter({ x: img.naturalWidth / 2, y: img.naturalHeight / 2 })
  }

  const rect = size ? cropRect(size, zoom, center) : null

  function changeZoom(next: number) {
    setZoom(next)
    if (size) setCenter(clampCenter(size, next, center))
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!size) return
    event.currentTarget.setPointerCapture?.(event.pointerId)
    drag.current = { x: event.clientX, y: event.clientY }
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const last = drag.current
    const box = event.currentTarget.getBoundingClientRect()
    if (!last || !size || !rect || box.width === 0 || box.height === 0) return
    drag.current = { x: event.clientX, y: event.clientY }
    const dx = event.clientX - last.x
    const dy = event.clientY - last.y
    setCenter((now) =>
      clampCenter(size, zoom, {
        x: now.x - (dx * rect.width) / box.width,
        y: now.y - (dy * rect.height) / box.height,
      }),
    )
  }

  async function save() {
    const img = imgRef.current
    if (!img || !rect) return
    setProblem(null)
    const canvas = document.createElement('canvas')
    canvas.width = OUT_WIDTH
    canvas.height = OUT_HEIGHT
    const context = canvas.getContext('2d')
    if (!context) {
      setProblem('Не удалось подготовить фото')
      return
    }
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, OUT_WIDTH, OUT_HEIGHT)
    context.drawImage(img, rect.x, rect.y, rect.width, rect.height, 0, 0, OUT_WIDTH, OUT_HEIGHT)
    const blob = await encodeJpeg(canvas)
    if (!blob) {
      setProblem('Фото слишком большое')
      return
    }
    const done = await action.run(async () => {
      await api.putPhoto(person.code, blob)
      return true
    })
    if (done) onSaved()
  }

  async function remove() {
    const done = await action.run(async () => {
      await api.deletePhoto(person.code)
      return true
    })
    setConfirmDelete(false)
    if (done) onSaved()
  }

  const shownError = problem ?? (action.error ? photoErrorText(action.error) : null)
  const locked = action.busy

  return (
    <>
      <Dialog title={`Фото ${person.code}`} onClose={onClose}>
        <div
          className="photo-frame"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
        >
          {camera ? (
            <video ref={videoRef} className="photo-video" autoPlay playsInline muted />
          ) : source ? (
            <img
              ref={imgRef}
              className="photo-source"
              src={source.url}
              alt={`Предпросмотр ${person.code}`}
              draggable={false}
              onLoad={imageLoaded}
              onError={() => setProblem('Не удалось открыть изображение')}
              style={
                size && rect
                  ? {
                      width: `${(size.width / rect.width) * 100}%`,
                      height: `${(size.height / rect.height) * 100}%`,
                      left: `${(-rect.x / rect.width) * 100}%`,
                      top: `${(-rect.y / rect.height) * 100}%`,
                    }
                  : { opacity: 0 }
              }
            />
          ) : person.has_photo ? (
            <img
              className="photo-current"
              src={photoUrl(person.code, person.photo_version)}
              alt={`Текущее фото ${person.code}`}
              draggable={false}
            />
          ) : (
            <span className="photo-empty photo-frame-empty">
              <PhotoPlaceholder />
            </span>
          )}
        </div>

        {source && (
          <label className="field photo-zoom">
            Масштаб
            <input
              type="range"
              min={MIN_ZOOM}
              max={MAX_ZOOM}
              step={0.05}
              value={zoom}
              disabled={!size || locked}
              onChange={(e) => changeZoom(Number(e.target.value))}
            />
          </label>
        )}
        {source && <p className="hint photo-hint">Перетащите фото, чтобы сдвинуть его в рамке.</p>}

        <div className="row photo-actions">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            aria-label="Файл фото"
            onChange={(e) => {
              chooseFile(e.target.files?.[0])
              e.target.value = ''
            }}
          />
          <button type="button" disabled={locked} onClick={() => fileRef.current?.click()}>
            Выбрать файл
          </button>
          {camera ? (
            <button type="button" className="primary" disabled={locked} onClick={() => void snapshot()}>
              Сделать снимок
            </button>
          ) : (
            <button type="button" disabled={locked} onClick={startCamera}>
              {source?.fromCamera ? 'Переснять' : 'Снять камерой'}
            </button>
          )}
        </div>

        <ErrorText error={shownError} />

        <div className="row photo-actions">
          <button
            type="button"
            className="primary"
            disabled={locked || !source || !size}
            onClick={() => void save()}
          >
            Сохранить
          </button>
          {person.has_photo && (
            <button type="button" disabled={locked} onClick={() => setConfirmDelete(true)}>
              Удалить фото
            </button>
          )}
        </div>
      </Dialog>
      {confirmDelete && (
        <ConfirmDialog
          title="Удалить фото"
          message={`Удалить фото ${person.code}?`}
          confirmLabel="Удалить"
          busy={action.busy}
          onConfirm={() => void remove()}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
    </>
  )
}
