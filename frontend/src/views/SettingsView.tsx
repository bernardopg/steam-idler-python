import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { ApiError, api, errorMessage } from '../api'
import { Icon } from '../components/Icon'
import type { SettingsDTO } from '../types'

type FieldType = 'text' | 'password' | 'secret' | 'number' | 'bool' | 'select' | 'textarea'

interface FieldSpec {
  key: string
  label: string
  type: FieldType
  options?: string[]
  hint?: string
  placeholder?: string
  min?: number
  max?: number
  step?: number
  multiline?: boolean
  /** Bool field that must be on for this field to matter. */
  enabledBy?: string
}

interface GroupSpec {
  title: string
  fields: FieldSpec[]
}

/** Sent by the backend in place of a saved secret; sending it back keeps the secret. */
const SECRET_MASK = '********'

// Every Settings field must appear here — mirrored by the backend parity test.
const GROUPS: GroupSpec[] = [
  {
    title: 'Credenciais',
    fields: [
      { key: 'username', label: 'Usuário Steam', type: 'text' },
      { key: 'password', label: 'Senha', type: 'password', hint: 'Em branco mantém a senha salva.' },
      {
        key: 'steam_api_key',
        label: 'Steam API Key',
        type: 'secret',
        hint: 'Opcional — melhora a detecção de cartas. steamcommunity.com/dev/apikey',
      },
      {
        key: 'steam_web_cookies',
        label: 'Cookies web',
        type: 'secret',
        multiline: true,
        placeholder: 'steamLoginSecure=…; sessionid=…',
        hint: 'k=v; k=v, JSON ou exportação do navegador. O steamLoginSecure precisa ser de audiência community.',
      },
    ],
  },
  {
    title: 'Jogos',
    fields: [
      { key: 'use_owned_games', label: 'Usar biblioteca da conta', type: 'bool' },
      { key: 'game_app_ids', label: 'App IDs manuais', type: 'text', placeholder: '570, 730', hint: 'Usados quando a biblioteca está desativada.' },
      { key: 'exclude_app_ids', label: 'App IDs excluídos', type: 'text', placeholder: '440', hint: 'Nunca fazer idle nestes.' },
      { key: 'filter_trading_cards', label: 'Só jogos com cartas', type: 'bool' },
      { key: 'filter_completed_card_drops', label: 'Pular drops concluídos', type: 'bool' },
      { key: 'max_games_to_idle', label: 'Máx. jogos simultâneos', type: 'number', min: 1, max: 32, hint: 'Limite da Steam: 32.' },
    ],
  },
  {
    title: 'Execução',
    fields: [
      {
        key: 'idling_backend',
        label: 'Backend',
        type: 'select',
        options: ['native', 'python', 'steam_utility'],
        hint: 'native: cliente Steam embutido (recomendado). python: biblioteca steam legada. steam_utility: usa o Steam instalado.',
      },
      { key: 'steam_utility_path', label: 'Caminho steam-utility', type: 'text', hint: 'Vazio = autodescoberta. Também usado no fallback dos backends native e python.' },
      {
        key: 'native_session_path',
        label: 'Sessão do backend native',
        type: 'text',
        hint: 'Guarda o refresh token (permissão 0600). Apague o arquivo para forçar novo login com Steam Guard.',
      },
      { key: 'refresh_interval_seconds', label: 'Refresh (s)', type: 'number', min: 10, hint: 'Intervalo para reavaliar os jogos.' },
      { key: 'checkpoint_minutes', label: 'Checkpoint (min)', type: 'number', min: 0, hint: '0 desativa.' },
      { key: 'duration_minutes', label: 'Duração máx. (min)', type: 'number', min: 0, hint: '0 = até interromper.' },
      { key: 'post_run_verify_seconds', label: 'Verificação pós-run (s)', type: 'number', min: 0, max: 600, hint: '0 desativa. Pular: clique em parar de novo.' },
    ],
  },
  {
    title: 'Rede & sessão',
    fields: [
      { key: 'api_timeout', label: 'Timeout API (s)', type: 'number', min: 1, max: 60 },
      { key: 'rate_limit_delay', label: 'Delay entre chamadas (s)', type: 'number', min: 0.1, max: 5, step: 0.1 },
      { key: 'max_checks', label: 'Máx. verificações de cartas', type: 'number', min: 1, max: 10000, hint: 'Vazio = sem limite.' },
      { key: 'skip_failures', label: 'Silenciar falhas de verificação', type: 'bool' },
      { key: 'auto_browser_cookies', label: 'Recuperar cookies do navegador', type: 'bool' },
      {
        key: 'browser_cookies_browser',
        label: 'Navegador',
        type: 'select',
        options: ['auto', 'chrome', 'firefox', 'edge', 'brave', 'chromium', 'opera', 'vivaldi', 'librewolf'],
        enabledBy: 'auto_browser_cookies',
      },
    ],
  },
  {
    title: 'Cache',
    fields: [
      { key: 'enable_card_cache', label: 'Cache de trading cards', type: 'bool' },
      { key: 'card_cache_path', label: 'Arquivo do cache de cartas', type: 'text', enabledBy: 'enable_card_cache' },
      { key: 'card_cache_ttl_days', label: 'TTL cartas (dias)', type: 'number', min: 1, max: 365, enabledBy: 'enable_card_cache' },
      { key: 'drop_cache_path', label: 'Arquivo do cache no-drop', type: 'text', enabledBy: 'enable_card_cache' },
      { key: 'drop_cache_ttl_days', label: 'TTL no-drop (dias)', type: 'number', min: 1, max: 365, enabledBy: 'enable_card_cache' },
    ],
  },
  {
    title: 'Logs',
    fields: [
      { key: 'log_level', label: 'Nível de log', type: 'select', options: ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] },
      { key: 'log_file', label: 'Arquivo de log', type: 'text', hint: 'Vazio = sem arquivo extra (cada execução já grava em logs/runs/).' },
    ],
  },
]

const ALL_FIELDS = GROUPS.flatMap((group) => group.fields)
export const SETTINGS_FIELD_KEYS = ALL_FIELDS.map((field) => field.key)

// Fields the backend requires as strings even when left blank.
const STRING_DEFAULTS: Record<string, string> = {
  game_app_ids: '',
  exclude_app_ids: '',
  steam_web_cookies: '',
  log_level: 'INFO',
  browser_cookies_browser: 'auto',
  card_cache_path: '.cache/trading_cards.json',
  drop_cache_path: '.cache/no_drop_cards.json',
  native_session_path: '.cache/steam_native_session.json',
}

type FormState = Record<string, string | boolean>

function toFormValue(value: unknown): string {
  if (value == null) return ''
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

function toPayload(form: FormState): SettingsDTO {
  const payload: SettingsDTO = {}
  for (const spec of ALL_FIELDS) {
    const value = form[spec.key]
    if (spec.type === 'bool') payload[spec.key] = Boolean(value)
    else if (spec.type === 'number') payload[spec.key] = value === '' ? null : Number(value)
    else {
      const text = String(value ?? '').trim()
      payload[spec.key] = spec.key in STRING_DEFAULTS ? text || STRING_DEFAULTS[spec.key] : text || null
    }
  }
  payload.username = String(form.username ?? '').trim()
  payload.password = String(form.password ?? '')
  return payload
}

export function SettingsView({ running }: { running: boolean }) {
  const [form, setForm] = useState<FormState>({})
  const [loaded, setLoaded] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const baselineRef = useRef<string>('')

  useEffect(() => {
    api
      .getSettings()
      .then(({ settings }) => {
        const next: FormState = {}
        for (const spec of ALL_FIELDS) {
          const raw = settings?.[spec.key]
          if (spec.type === 'bool') next[spec.key] = Boolean(raw ?? false)
          else if (spec.type === 'password') next[spec.key] = ''
          else next[spec.key] = toFormValue(raw)
        }
        setForm(next)
        baselineRef.current = JSON.stringify(next)
        setLoaded(true)
      })
      .catch((exc) => setMessage({ tone: 'err', text: errorMessage(exc) }))
  }, [])

  const dirty = loaded && JSON.stringify(form) !== baselineRef.current

  // Warn before closing the tab with unsaved edits.
  useEffect(() => {
    if (!dirty) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  function update(key: string, value: string | boolean) {
    setForm((current) => ({ ...current, [key]: value }))
    setFieldErrors((current) => {
      if (!(key in current)) return current
      const next = { ...current }
      delete next[key]
      return next
    })
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!event.currentTarget.reportValidity()) return
    setSaving(true)
    setMessage(null)
    setFieldErrors({})
    try {
      const result = await api.putSettings(toPayload(form))
      // The password field is write-only: clear it once saved.
      const saved = { ...form, password: '' }
      setForm(saved)
      baselineRef.current = JSON.stringify(saved)
      setMessage({ tone: 'ok', text: `Salvo em ${result.path}${running ? ' — vale a partir do próximo início.' : '.'}` })
    } catch (exc) {
      if (exc instanceof ApiError && exc.fieldErrors.length > 0) {
        setFieldErrors(Object.fromEntries(exc.fieldErrors.map((error) => [error.field, error.message])))
        setMessage({ tone: 'err', text: 'Corrija os campos destacados.' })
      } else {
        setMessage({ tone: 'err', text: errorMessage(exc) })
      }
    } finally {
      setSaving(false)
    }
  }

  if (!loaded) {
    return message ? (
      <p className="text-sm text-err" role="alert">
        Não foi possível carregar as configurações: {message.text}
      </p>
    ) : (
      <p className="text-dim">Carregando configurações…</p>
    )
  }

  return (
    <form onSubmit={save} className="max-w-3xl space-y-6">
      {running && (
        <p className="rounded-lg border border-info/30 bg-info/10 px-4 py-3 text-sm text-info">
          O bot está rodando: mudanças salvas valem a partir do próximo início.
        </p>
      )}
      {GROUPS.map((group) => (
        <fieldset key={group.title} className="rounded-xl border border-edge-soft bg-surface p-5">
          <legend className="px-1 text-sm font-semibold uppercase tracking-widest text-em-soft">{group.title}</legend>
          <div className="mt-2 grid gap-4 sm:grid-cols-2">
            {group.fields.map((spec) => (
              <Field
                key={spec.key}
                spec={spec}
                value={form[spec.key]}
                error={fieldErrors[spec.key]}
                disabled={spec.enabledBy ? !form[spec.enabledBy] : false}
                onChange={(value) => update(spec.key, value)}
              />
            ))}
          </div>
        </fieldset>
      ))}
      <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-4 bg-bg/90 px-1 py-4 backdrop-blur">
        <button
          type="submit"
          disabled={saving || !dirty}
          className="rounded-lg bg-em px-8 py-2.5 font-semibold text-bg transition hover:bg-em-bright disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? 'Salvando…' : 'Salvar no .env'}
        </button>
        {dirty && !saving && <span className="text-xs font-medium text-warn">● Alterações não salvas</span>}
        {message && (
          <p className={`text-sm ${message.tone === 'ok' ? 'text-em-bright' : 'text-err'}`} role={message.tone === 'err' ? 'alert' : 'status'}>
            {message.text}
          </p>
        )}
      </div>
    </form>
  )
}

interface FieldProps {
  spec: FieldSpec
  value: string | boolean | undefined
  error?: string
  disabled: boolean
  onChange: (value: string | boolean) => void
}

const inputClass =
  'w-full rounded-lg border bg-raised px-3 py-2 text-sm text-ink outline-none transition placeholder:text-dim focus:border-em disabled:cursor-not-allowed disabled:opacity-40'

function Field({ spec, value, error, disabled, onChange }: FieldProps) {
  const id = `setting-${spec.key}`
  const describedBy = [error && `${id}-error`, spec.hint && `${id}-hint`].filter(Boolean).join(' ') || undefined
  const border = error ? 'border-err' : 'border-edge'
  const wide = spec.type === 'textarea' || spec.multiline

  if (spec.type === 'bool') {
    return (
      <div>
        <label
          htmlFor={id}
          className="flex cursor-pointer items-center gap-3 rounded-lg border border-edge-soft bg-raised px-3 py-2.5 text-sm"
        >
          <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} aria-describedby={describedBy} />
          <span>{spec.label}</span>
        </label>
        <FieldNotes id={id} hint={spec.hint} error={error} />
      </div>
    )
  }

  let control: ReactNode
  if (spec.type === 'secret') {
    control = <SecretInput id={id} spec={spec} value={String(value ?? '')} className={`${inputClass} ${border}`} describedBy={describedBy} onChange={onChange} />
  } else if (spec.type === 'select') {
    control = (
      <select id={id} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} disabled={disabled} aria-describedby={describedBy} className={`${inputClass} ${border}`}>
        {spec.options?.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    )
  } else {
    control = (
      <input
        id={id}
        type={spec.type}
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        min={spec.min}
        max={spec.max}
        step={spec.step}
        required={spec.key === 'username'}
        disabled={disabled}
        placeholder={spec.placeholder}
        autoComplete={spec.type === 'password' ? 'current-password' : spec.key === 'username' ? 'username' : 'off'}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={`${inputClass} ${border} ${spec.type === 'number' ? 'tnum' : ''}`}
      />
    )
  }

  return (
    <div className={wide ? 'sm:col-span-2' : ''}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium uppercase tracking-wider text-dim">
        {spec.label}
      </label>
      {control}
      <FieldNotes id={id} hint={spec.hint} error={error} />
    </div>
  )
}

function FieldNotes({ id, hint, error }: { id: string; hint?: string; error?: string }) {
  return (
    <>
      {error && (
        <span id={`${id}-error`} className="mt-1 block text-xs text-err">
          {error}
        </span>
      )}
      {hint && (
        <span id={`${id}-hint`} className="mt-1 block text-xs text-dim">
          {hint}
        </span>
      )}
    </>
  )
}

interface SecretInputProps {
  id: string
  spec: FieldSpec
  value: string
  className: string
  describedBy?: string
  onChange: (value: string) => void
}

/**
 * A saved secret is never sent to the browser: the backend returns a mask,
 * which is sent back untouched to keep the value. "Alterar" swaps in an empty
 * input (blank on save = remove); "Manter atual" restores the mask.
 */
function SecretInput({ id, spec, value, className, describedBy, onChange }: SecretInputProps) {
  const [wasSaved] = useState(value === SECRET_MASK)

  if (value === SECRET_MASK) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-edge-soft bg-raised px-3 py-2 text-sm">
        <Icon name="eye" className="h-4 w-4 text-dim" />
        <span className="font-mono text-mut">•••••••• salvo</span>
        <button type="button" id={id} aria-label={`Alterar ${spec.label}`} onClick={() => onChange('')} className="ml-auto text-xs font-semibold text-em-soft hover:text-em-bright">
          Alterar
        </button>
      </div>
    )
  }

  const keep = wasSaved && (
    <button type="button" onClick={() => onChange(SECRET_MASK)} className="mt-1 text-xs font-semibold text-em-soft hover:text-em-bright">
      Manter o valor salvo
    </button>
  )
  const common = {
    id,
    value,
    placeholder: spec.placeholder ?? (wasSaved ? 'Em branco remove o valor salvo' : undefined),
    autoComplete: 'off',
    spellCheck: false,
    'aria-describedby': describedBy,
    className: `${className} font-mono text-xs`,
  }
  return (
    <>
      {spec.multiline ? (
        <textarea {...common} rows={3} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input {...common} type="password" onChange={(e) => onChange(e.target.value)} />
      )}
      {keep}
    </>
  )
}
