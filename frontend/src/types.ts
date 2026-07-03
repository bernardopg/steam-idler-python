export interface GameRow {
  app_id: number
  name: string
  cards_remaining: number | null
  drops: number
  idle_minutes: number
}

export interface Snapshot {
  status: 'stopped' | 'starting' | 'running' | 'stopping' | 'error'
  running: boolean
  dry_run: boolean
  account: string | null
  session_minutes: number
  games: GameRow[]
  games_count: number
  cards_remaining_known: number | null
  session_drops: number
  auth_pending: boolean
  last_error: string | null
}

export interface LogLine {
  level: string
  line: string
}

export interface AuthRequest {
  is_2fa: boolean
  code_mismatch: boolean
}

export type SettingsDTO = Record<string, unknown>
