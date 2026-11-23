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
}

export interface SetupFields extends SetupFormView {
  token: string
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
    }

export interface StatusView {
  pending: number
  rejected: number
  online: boolean | null
}

export interface Snapshot {
  camera?: string | null
  discipline: string
  players_needed: number
  status: StatusView
  state: StateView
}

export type Command =
  | { action: 'type_char' | 'enter_code'; value: string }
  | { action: 'setup_check' | 'setup_save'; value: SetupFields }
  | {
      action:
        | 'backspace'
        | 'submit_input'
        | 'confirm'
        | 'cancel'
        | 'retry'
        | 'give_up'
        | 'show_rejected'
        | 'close_rejected'
        | 'export_rejected'
    }
