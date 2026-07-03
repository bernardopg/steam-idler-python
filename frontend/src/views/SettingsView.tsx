import { useEffect, useState } from 'react'
import { api } from '../api'
import type { SettingsDTO } from '../types'

type FieldType = 'text' | 'password' | 'number' | 'bool' | 'select' | 'textarea'

interface FieldSpec {
  key: string
  label: string
  type: FieldType
  options?: string[]
  hint?: string
  min?: number
  max?: number
  step?: number
}

interface GroupSpec {
  title: string
  fields: FieldSpec[]
}

// Every Settings field must appear here — mirrored by the backend parity test.
const GROUPS: GroupSpec[] = [
  {
    title: 'Credenciais',
    fields: [
      { key: 'username', label: 'Usuário Steam', type: 'text' },
      { key: 'password', label: 'Senha', type: 'password', hint: 'Em branco mantém a senha salva' },
      { key: 'steam_api_key', label: 'Steam API Key', type: 'text', hint: 'Opcional — melhora a detecção de cartas' },
      { key: 'steam_web_cookies', label: 'Cookies web', type: 'textarea', hint: 'k=v; k=v — steamLoginSecure de audiência community' },
    ],
  },
  {
    title: 'Jogos',
    fields: [
      { key: 'use_owned_games', label: 'Usar biblioteca da conta', type: 'bool' },
      { key: 'game_app_ids', label: 'App IDs manuais', type: 'text', hint: 'CSV — usado quando a biblioteca está desativada' },
      { key: 'exclude_app_ids', label: 'App IDs excluídos', type: 'text', hint: 'CSV — nunca fazer idle nestes' },
      { key: 'filter_trading_cards', label: 'Só jogos com cartas', type: 'bool' },
      { key: 'filter_completed_card_drops', label: 'Pular drops concluídos', type: 'bool' },
      { key: 'max_games_to_idle', label: 'Máx. jogos simultâneos', type: 'number', min: 1, max: 32 },
    ],
  },
  {
    title: 'Execução',
    fields: [
      { key: 'idling_backend', label: 'Backend', type: 'select', options: ['python', 'steam_utility'] },
      { key: 'steam_utility_path', label: 'Caminho steam-utility', type: 'text', hint: 'Vazio = autodescoberta' },
      { key: 'refresh_interval_seconds', label: 'Refresh (s)', type: 'number', min: 10 },
      { key: 'checkpoint_minutes', label: 'Checkpoint (min)', type: 'number', min: 0, hint: '0 desativa' },
      { key: 'duration_minutes', label: 'Duração máx. (min)', type: 'number', min: 0, hint: '0 = até interromper' },
      { key: 'post_run_verify_seconds', label: 'Verificação pós-run (s)', type: 'number', min: 0, max: 600 },
    ],
  },
  {
    title: 'Rede & sessão',
    fields: [
      { key: 'api_timeout', label: 'Timeout API (s)', type: 'number', min: 1, max: 60 },
      { key: 'rate_limit_delay', label: 'Delay entre chamadas (s)', type: 'number', min: 0.1, max: 5, step: 0.1 },
      { key: 'max_checks', label: 'Máx. verificações de cartas', type: 'number', min: 1, hint: 'Vazio = sem limite' },
      { key: 'skip_failures', label: 'Silenciar falhas de verificação', type: 'bool' },
      { key: 'auto_browser_cookies', label: 'Recuperar cookies do navegador', type: 'bool' },
      {
        key: 'browser_cookies_browser',
        label: 'Navegador',
        type: 'select',
        options: ['auto', 'chrome', 'firefox', 'edge', 'brave', 'chromium', 'opera', 'vivaldi', 'librewolf'],
      },
    ],
  },
  {
    title: 'Cache',
    fields: [
      { key: 'enable_card_cache', label: 'Cache de trading cards', type: 'bool' },
      { key: 'card_cache_path', label: 'Arquivo do cache de cartas', type: 'text' },
      { key: 'card_cache_ttl_days', label: 'TTL cartas (dias)', type: 'number', min: 1, max: 365 },
      { key: 'drop_cache_path', label: 'Arquivo do cache no-drop', type: 'text' },
      { key: 'drop_cache_ttl_days', label: 'TTL no-drop (dias)', type: 'number', min: 1, max: 365 },
    ],
  },
  {
    title: 'Logs & segurança',
    fields: [
      { key: 'log_level', label: 'Nível de log', type: 'select', options: ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] },
      { key: 'log_file', label: 'Arquivo de log', type: 'text', hint: 'Vazio = sem arquivo extra' },
      { key: 'enable_encryption', label: 'Criptografar credenciais', type: 'bool' },
    ],
  },
]

export const SETTINGS_FIELD_KEYS = GROUPS.flatMap((group) => group.fields.map((field) => field.key))

function toFormValue(value: unknown): string {
  if (value == null) return ''
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

export function SettingsView() {
  const [form, setForm] = useState<Record<string, string | boolean>>({})
  const [loaded, setLoaded] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .getSettings()
      .then(({ settings }) => {
        const next: Record<string, string | boolean> = {}
        for (const spec of GROUPS.flatMap((g) => g.fields)) {
          const raw = settings?.[spec.key]
          next[spec.key] = spec.type === 'bool' ? Boolean(raw ?? false) : spec.key === 'password' ? '' : toFormValue(raw)
        }
        setForm(next)
        setLoaded(true)
      })
      .catch((exc) => setMessage({ tone: 'err', text: String(exc) }))
  }, [])

  async function save() {
    setSaving(true)
    setMessage(null)
    const payload: SettingsDTO = {}
    for (const spec of GROUPS.flatMap((g) => g.fields)) {
      const value = form[spec.key]
      if (spec.type === 'bool') payload[spec.key] = Boolean(value)
      else if (spec.type === 'number') payload[spec.key] = value === '' ? null : Number(value)
      else payload[spec.key] = typeof value === 'string' ? value.trim() || null : value
    }
    // Required/list fields must not be null
    payload.username = String(form.username ?? '')
    payload.password = String(form.password ?? '')
    payload.game_app_ids = String(form.game_app_ids ?? '')
    payload.exclude_app_ids = String(form.exclude_app_ids ?? '')
    payload.steam_web_cookies = String(form.steam_web_cookies ?? '')
    payload.log_level = String(form.log_level || 'INFO')
    payload.browser_cookies_browser = String(form.browser_cookies_browser || 'auto')
    payload.card_cache_path = String(form.card_cache_path || '.cache/trading_cards.json')
    payload.drop_cache_path = String(form.drop_cache_path || '.cache/no_drop_cards.json')
    try {
      const result = await api.putSettings(payload)
      setMessage({ tone: 'ok', text: `Salvo em ${result.path}` })
    } catch (exc) {
      setMessage({ tone: 'err', text: String(exc) })
    } finally {
      setSaving(false)
    }
  }

  if (!loaded && !message) return <p className="text-dim">Carregando configurações…</p>

  return (
    <div className="max-w-3xl space-y-6">
      {GROUPS.map((group) => (
        <section key={group.title} className="rounded-xl border border-edge-soft bg-surface p-5">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-em-soft">{group.title}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {group.fields.map((spec) => (
              <Field
                key={spec.key}
                spec={spec}
                value={form[spec.key]}
                onChange={(value) => setForm((f) => ({ ...f, [spec.key]: value }))}
              />
            ))}
          </div>
        </section>
      ))}
      <div className="flex items-center gap-4 pb-8">
        <button
          onClick={save}
          disabled={saving}
          className="rounded-lg bg-em px-8 py-2.5 font-semibold text-bg transition hover:bg-em-bright disabled:opacity-40"
        >
          {saving ? 'Salvando…' : 'Salvar no .env'}
        </button>
        {message && <p className={`text-sm ${message.tone === 'ok' ? 'text-em-bright' : 'text-err'}`}>{message.text}</p>}
      </div>
    </div>
  )
}

interface FieldProps {
  spec: FieldSpec
  value: string | boolean | undefined
  onChange: (value: string | boolean) => void
}

function Field({ spec, value, onChange }: FieldProps) {
  const inputClass =
    'w-full rounded-lg border border-edge bg-raised px-3 py-2 text-sm text-ink outline-none transition focus:border-em placeholder:text-dim'

  if (spec.type === 'bool') {
    return (
      <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-edge-soft bg-raised px-3 py-2.5 text-sm">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span>{spec.label}</span>
      </label>
    )
  }

  return (
    <label className={`block text-sm ${spec.type === 'textarea' ? 'sm:col-span-2' : ''}`}>
      <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-dim">{spec.label}</span>
      {spec.type === 'select' ? (
        <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} className={inputClass}>
          {spec.options?.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : spec.type === 'textarea' ? (
        <textarea
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
          placeholder={spec.hint}
          className={`${inputClass} font-mono text-xs`}
        />
      ) : (
        <input
          type={spec.type}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          min={spec.min}
          max={spec.max}
          step={spec.step}
          placeholder={spec.hint}
          className={inputClass}
        />
      )}
      {spec.hint && spec.type !== 'textarea' && spec.type !== 'text' && spec.type !== 'password' && (
        <span className="mt-1 block text-xs text-dim">{spec.hint}</span>
      )}
    </label>
  )
}
