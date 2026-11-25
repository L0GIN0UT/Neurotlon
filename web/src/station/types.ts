// Снимок состояния станции от лаунчера (launcher/src/neurotlon_launcher/snapshot.py).

export interface TeamView {
  number: number
  name: string
  color: string
}

export interface CandidateView {
  code: string
  display_name: string | null
  team: TeamView | null
  issues: string[]
  offline: boolean
  warned: boolean
}

export interface RejectedItem {
  session_id: string
  codes: string[]
  error: string
}

export interface SetupFormView {
  server_url: string
  game_path: string
  ca_file: string
  camera: string
  sensors: string
  /** Старые ядра ещё присылают; веб его не читает и не отправляет. */
  devices?: Record<string, string>
  eeg_method: string
}

export type SensorLinkState = 'connecting' | 'connected' | 'failed' | 'lost'

/** Устройство из фонового поиска ядра. Назначенные идут первыми, остальные по времени обнаружения. */
export interface SensorEntry {
  id: string
  name: string
  kind: 'brainbit' | 'callibri'
  serial: string | null
  address: string
  rssi: number | null
  in_range: boolean
  age_s: number
  role: string | null
  link: SensorLinkState | null
  battery: number | null
  contact: boolean | null
  signal: boolean | null
  level: number | null
  /** Причина сбоя по-русски (при `link === 'failed'`). */
  error: string | null
}

export interface SensorsView {
  phase: 'idle' | 'scanning' | 'stopped' | 'error'
  error: string | null
  devices: SensorEntry[]
}

/** Старый результат блокирующего поиска; уйдёт вместе с `sensors_scan` в PR-уборке ядра. */
export interface SensorDevice {
  kind: string
  name: string
  serial: string
  address: string
}

export type SetupFields = Omit<SetupFormView, 'devices'> & {
  token: string
}

export type CalibrationStatus = 'pending' | 'running' | 'done' | 'failed'
export type CalibrationPhase = 'tense' | 'relax'

export interface SensorView {
  signal: string
  state: string
  battery: number | null
}

export interface CalibrationPartView {
  signal: string
  status: CalibrationStatus
  progress: number
  reason_text: string | null
}

export interface CalibrationStepView {
  id: string
  step: 'cycle' | 'baseline'
  signals: string[]
  status: CalibrationStatus
  progress: number
  segment: number
  segments_total: number
  phase: CalibrationPhase | null
  phase_left_s: number | null
  reason_text: string | null
  /** Статус и причина по каждому сигналу шага (в понге по игроку). */
  parts?: CalibrationPartView[]
}

export type StateView =
  | { kind: 'idle'; input: string; notice: string | null; taken: CandidateView[] }
  | { kind: 'checking'; code: string; taken: CandidateView[] }
  | {
      kind: 'confirm'
      candidate: CandidateView
      taken: CandidateView[]
      notice: string | null
      is_last: boolean
    }
  | { kind: 'starting'; players: CandidateView[] }
  | {
      kind: 'calibrating'
      players: CandidateView[]
      link: 'connecting' | 'live' | 'lost'
      sensors: SensorView[]
      eeg_method: string | null
      steps: CalibrationStepView[]
      current: string | number | null
      ready: boolean
    }
  | { kind: 'playing'; players: CandidateView[]; offline: boolean; default_limit: boolean }
  | { kind: 'done'; lines: string[]; seconds_left: number; seconds_total: number }
  | { kind: 'problem'; reason: string; players: CandidateView[] }
  | { kind: 'blocked'; message: string }
  | { kind: 'rejected'; items: RejectedItem[]; exported_to: string | null }
  | {
      kind: 'setup'
      phase: 'form' | 'checking' | 'ok' | 'saved'
      error: string | null
      discipline: string | null
      players_needed: number | null
      form: SetupFormView
      has_token: boolean
      games_bundled: boolean
      game: string
      sensors_available: boolean
      roles: string[]
      /** Живой поиск датчиков; у старого ядра поля нет. */
      sensors?: SensorsView
      scan: {
        seconds: number
        phase: 'idle' | 'scanning' | 'done'
        devices: SensorDevice[]
        error: string | null
      }
    }

export interface StatusView {
  pending: number
  rejected: number
  online: boolean | null
}

export interface Snapshot {
  camera?: string | null
  sensors?: { mode: string; ok: boolean; error: string | null } | null
  discipline: string
  players_needed: number
  status: StatusView
  state: StateView
}

export type Command =
  | { action: 'type_char' | 'enter_code' | 'calibration_retry'; value: string }
  | { action: 'setup_check' | 'setup_save'; value: SetupFields }
  | { action: 'sensors_scan_start' | 'sensors_scan_stop'; value?: undefined }
  | { action: 'sensors_assign'; value: { role: string; id: string } }
  | { action: 'sensors_unassign'; value: { role: string } }
  | {
      action:
        | 'backspace'
        | 'submit_input'
        | 'confirm'
        | 'cancel'
        | 'retry'
        | 'back'
        | 'calibration_continue'
        | 'calibration_restart'
        | 'show_rejected'
        | 'close_rejected'
        | 'export_rejected'
    }
