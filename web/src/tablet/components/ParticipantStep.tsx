import { useState } from 'react'
import type { FormEvent } from 'react'
import { normalizeCode } from '../participantCode.ts'
import { QrScanner } from './QrScanner.tsx'

interface Props {
  /** 1 для дартса и футбола, 2 для понга. */
  slots: 1 | 2
  onNext: (codes: string[]) => void
}

export function ParticipantStep({ slots, onNext }: Props) {
  const [codes, setCodes] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)

  function add(raw: string): boolean {
    const code = normalizeCode(raw)
    if (!code) {
      setError('Это не ID участника. Формат: NT07 или просто 7')
      return false
    }
    if (codes.includes(code)) {
      setError(`${code} уже добавлен`)
      return false
    }
    if (codes.length >= slots && slots === 2) {
      setError('Уже выбраны два игрока')
      return false
    }
    setError(null)
    setCodes(slots === 1 ? [code] : [...codes, code])
    return true
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (add(input)) setInput('')
  }

  function scanned(text: string) {
    if (add(text)) setScanning(false)
  }

  const label = slots === 2 ? 'ID игрока' : 'ID участника'
  return (
    <section className="card stack">
      <h1>{slots === 2 ? 'Игроки матча' : 'Участник'}</h1>
      <form className="row" onSubmit={submit}>
        <label className="field grow">
          {label}
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            inputMode="text"
            autoCapitalize="characters"
            placeholder="NT07"
          />
        </label>
        <button type="submit">Добавить</button>
      </form>
      <button type="button" onClick={() => setScanning((on) => !on)}>
        {scanning ? 'Скрыть камеру' : 'Сканировать QR'}
      </button>
      {scanning && <QrScanner onCode={scanned} onClose={() => setScanning(false)} />}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <ul className="chips" aria-label="Выбранные участники">
        {codes.map((code) => (
          <li key={code}>
            <strong>{code}</strong>
            <button
              type="button"
              aria-label={`Убрать ${code}`}
              onClick={() => setCodes(codes.filter((c) => c !== code))}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="primary"
        disabled={codes.length !== slots}
        onClick={() => onNext(codes)}
      >
        Далее
      </button>
    </section>
  )
}
