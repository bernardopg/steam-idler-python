import { useEffect, useRef, useState } from 'react'
import type { AuthRequest, LogLine, SettingsDTO, Snapshot } from './types'

const MAX_LOG_LINES = 2000

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep the HTTP status text */
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
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

/** Live bot state over a self-reconnecting WebSocket. */
export function useBot(): BotState & { clearLogs: () => void; dismissAuth: () => void } {
  const [state, setState] = useState<BotState>(initialState)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let disposed = false
    let retryTimer: number | undefined

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const socket = new WebSocket(`${protocol}://${window.location.host}/api/ws`)
      socketRef.current = socket

      socket.onopen = () => setState((s) => ({ ...s, connected: true }))

      socket.onmessage = (message) => {
        const event = JSON.parse(message.data)
        setState((s) => {
          switch (event.type) {
            case 'init':
              return {
                ...s,
                snapshot: event.snapshot,
                logs: event.logs ?? [],
                report: event.report ?? '',
                authRequest: event.auth_pending ? { is_2fa: true, code_mismatch: false } : null,
              }
            case 'snapshot':
              return { ...s, snapshot: event.snapshot }
            case 'log':
              return { ...s, logs: [...s.logs.slice(-MAX_LOG_LINES + 1), { level: event.level, line: event.line }] }
            case 'status':
              return s.snapshot ? { ...s, snapshot: { ...s.snapshot, status: event.state } } : s
            case 'report':
            case 'finished':
              return { ...s, report: event.report ?? event.text ?? s.report, authRequest: null }
            case 'auth_request':
              return { ...s, authRequest: { is_2fa: event.is_2fa, code_mismatch: event.code_mismatch } }
            case 'error':
              return {
                ...s,
                logs: [...s.logs.slice(-MAX_LOG_LINES + 1), { level: 'ERROR', line: event.message }],
              }
            default:
              return s
          }
        })
      }

      socket.onclose = () => {
        setState((s) => ({ ...s, connected: false }))
        if (!disposed) retryTimer = window.setTimeout(connect, 2000)
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
