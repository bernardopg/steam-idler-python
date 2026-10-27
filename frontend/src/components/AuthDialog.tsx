import { type FormEvent, useState } from 'react'
import { api, errorMessage } from '../api'
import type { AuthRequest } from '../types'

interface AuthDialogProps {
  request: AuthRequest
  onDone: () => void
}

export function AuthDialog({ request, onDone }: AuthDialogProps) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || !code.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.sendAuthCode(code.trim())
      onDone()
    } catch (exc) {
      setError(errorMessage(exc))
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    // An empty code tells the backend login flow to abort cleanly (treated as
    // "Authentication code entry cancelled"), which stops the bot instead of
    // leaving the worker thread blocked forever on this prompt.
    setBusy(true)
    try {
      await api.sendAuthCode('')
    } catch {
      /* the bot may already have stopped; either way there's nothing to retry */
    } finally {
      onDone()
    }
  }

  const prompt = request.is_2fa ? 'Digite o código do app Steam Mobile.' : 'Digite o código enviado por e-mail.'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 p-4 backdrop-blur-sm">
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
        aria-describedby="auth-desc"
        className="w-full max-w-sm rounded-2xl border border-edge bg-raised p-6 shadow-2xl"
      >
        <h2 id="auth-title" className="text-lg font-semibold text-em-soft">
          Steam Guard
        </h2>
        <p id="auth-desc" className="mt-1 text-sm text-mut">
          {request.code_mismatch ? <span className="text-warn">Código incorreto — tente novamente. </span> : null}
          {prompt}
        </p>
        <label htmlFor="auth-code" className="sr-only">
          Código Steam Guard
        </label>
        <input
          id="auth-code"
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase().replace(/\s/g, ''))}
          placeholder="XXXXX"
          maxLength={8}
          autoComplete="one-time-code"
          autoCapitalize="characters"
          spellCheck={false}
          className="tnum mt-4 w-full rounded-lg border border-edge bg-surface px-4 py-3 text-center font-mono text-xl tracking-[0.4em] text-em-bright outline-none focus:border-em"
        />
        {error && (
          <p className="mt-2 text-sm text-err" role="alert">
            {error}
          </p>
        )}
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={cancel}
            disabled={busy}
            className="flex-1 rounded-lg border border-edge px-4 py-2.5 font-semibold text-mut transition hover:border-err hover:text-err disabled:cursor-not-allowed disabled:opacity-40"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={busy || !code.trim()}
            className="flex-1 rounded-lg bg-em px-4 py-2.5 font-semibold text-bg transition hover:bg-em-bright disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? 'Enviando…' : 'Confirmar'}
          </button>
        </div>
        <p className="mt-3 text-center text-xs text-dim">Cancelar interrompe o bot, já que o login ficará pendente.</p>
      </form>
    </div>
  )
}
