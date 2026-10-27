import { useEffect, useRef, useState } from 'react'
import type { AuthRequest, FieldError, LogLine, SettingsDTO, Snapshot } from './types'

const MAX_LOG_LINES = 2000
const RECONNECT_MIN_MS = 1000
const RECONNECT_MAX_MS = 15000

/** An API failure with a readable message and, for 422s, per-field errors. */
export class ApiError extends Error {
  readonly status: number
  readonly fieldErrors: FieldError[]

  constructor(message: string, status: number, fieldErrors: FieldError[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

/** Accepts our `{field, message}` items and FastAPI's own `{loc, msg}` ones. */
function toFieldErrors(detail: unknown): FieldError[] {
  if (!Array.isArray(detail)) return []
  return detail.flatMap((item): FieldError[] => {
    if (typeof item !== 'object' || item === null) return []
    const record = item as Record<string, unknown>
    if (typeof record.field === 'string' && typeof record.message === 'string') {
      return [{ field: record.field, message: record.message }]
    }
    if (Array.isArray(record.loc) && typeof record.msg === 'string') {
      return [{ field: record.loc.filter((part) => part !== 'body').join('.'), message: record.msg }]
    }
    return []
  })
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  } catch {
    throw new ApiError('Servidor inacessível. O processo do bot ainda está rodando?', 0)
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    let fieldErrors: FieldError[] = []
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      fieldErrors = toFieldErrors(body.detail)
      if (fieldErrors.length > 0) message = fieldErrors.map((error) => `${error.field}: ${error.message}`).join(' · ')
    } catch {
      /* keep the HTTP status text */
    }
    throw new ApiError(message, response.status, fieldErrors)
  }
  return response.json() as Promise<T>
}

export function errorMessage(exc: unknown): string {
  return exc instanceof Error ? exc.message : String(exc)
}

export const api = {
  getSettings: () => request<{ configured: boolean; settings: SettingsDTO | null }>('/api/settings'),
  putSettings: (settings: SettingsDTO) =>
    request<{ saved: boolean; path: string }>('/api/settings', { method: 'PUT', body: JSON.stringify(settings) }),
  startBot: (dryRun: boolean) =>
    request<{ started: boolean }>('/api/bot/start', { method: 'POST', body: JSON.stringify({ dry_run: dryRun }) }),
  stopBot: () => request<{ stopping: boolean }>('/api/bot/stop', { method: 'POST', body: JSON.stringify({}) }),
  sendAuthCode: (code: string) =>
    request<{ delivered: boolean }>('/api/auth-code', { method: 'POST', body: JSON.stringify({ code }) }),
  stopAppIds: (appIds: number[]) =>
    request<{ status: number }>('/api/stop-app-ids', { method: 'POST', body: JSON.stringify({ app_ids: appIds }) }),
}

export interface BotState {
  connected: boolean
  snapshot: Snapshot | null
  logs: LogLine[]
  report: string
  authRequest: AuthRequest | null
}

const initialState: BotState = {
  connected: false,
  snapshot: null,
  logs: [],
  report: '',
  authRequest: null,
}

/** Live bot state over a self-reconnecting WebSocket (exponential backoff). */
export function useBot(): BotState & { clearLogs: () => void; dismissAuth: () => void } {
  const [state, setState] = useState<BotState>(initialState)
  const socketRef = useRef<WebSocket | null>(null)
  const logIdRef = useRef(0)

  useEffect(() => {
    let disposed = false
    let retryTimer: number | undefined
    let retryDelay = RECONNECT_MIN_MS

    const toLogLine = (level: string, line: string): LogLine => ({ id: ++logIdRef.current, level, line })
    const appendLog = (logs: LogLine[], entry: LogLine) => [...logs.slice(-MAX_LOG_LINES + 1), entry]

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const socket = new WebSocket(`${protocol}://${window.location.host}/api/ws`)
      socketRef.current = socket

      socket.onopen = () => {
        retryDelay = RECONNECT_MIN_MS
        setState((s) => ({ ...s, connected: true }))
      }

      socket.onmessage = (message) => {
        const event = JSON.parse(message.data)
        setState((s) => {
          switch (event.type) {
            case 'init':
              return {
                ...s,
                snapshot: event.snapshot,
                logs: (event.logs ?? []).map((log: { level: string; line: string }) => toLogLine(log.level, log.line)),
                report: event.report ?? '',
                authRequest: event.auth_request ?? null,
              }
            case 'snapshot':
              return { ...s, snapshot: event.snapshot }
            case 'log':
              return { ...s, logs: appendLog(s.logs, toLogLine(event.level, event.line)) }
            case 'status':
              return s.snapshot ? { ...s, snapshot: { ...s.snapshot, status: event.state } } : s
            case 'report':
              return { ...s, report: event.text ?? s.report }
            case 'finished':
              return { ...s, report: event.report || s.report, authRequest: null }
            case 'auth_request':
              return { ...s, authRequest: { is_2fa: event.is_2fa, code_mismatch: event.code_mismatch } }
            case 'error':
              return { ...s, logs: appendLog(s.logs, toLogLine('ERROR', event.message)) }
            default:
              return s
          }
        })
      }

      socket.onclose = () => {
        setState((s) => ({ ...s, connected: false }))
        if (disposed) return
        retryTimer = window.setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, RECONNECT_MAX_MS)
      }
    }

    connect()
    return () => {
      disposed = true
      if (retryTimer) window.clearTimeout(retryTimer)
      socketRef.current?.close()
    }
  }, [])

  return {
    ...state,
    clearLogs: () => setState((s) => ({ ...s, logs: [] })),
    dismissAuth: () => setState((s) => ({ ...s, authRequest: null })),
  }
}
