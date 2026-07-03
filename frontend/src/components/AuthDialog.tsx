import { useState } from 'react'
import { api } from '../api'
import type { AuthRequest } from '../types'

interface AuthDialogProps {
  request: AuthRequest
  onDone: () => void
}

export function AuthDialog({ request, onDone }: AuthDialogProps) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    try {
      await api.sendAuthCode(code)
      onDone()
    } catch (exc) {
      setError(String(exc))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-2xl border border-edge bg-raised p-6 shadow-2xl">
        <h2 className="text-lg font-semibold text-em-soft">Steam Guard</h2>
        <p className="mt-1 text-sm text-mut">
          {request.code_mismatch
            ? 'Código incorreto — tente novamente.'
            : request.is_2fa
              ? 'Digite o código do app Steam Mobile.'
              : 'Digite o código enviado por e-mail.'}
        </p>
        <input
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="XXXXX"
          className="tnum mt-4 w-full rounded-lg border border-edge bg-surface px-4 py-3 text-center font-mono text-xl tracking-[0.4em] text-em-bright outline-none focus:border-em"
        />
        {error && <p className="mt-2 text-sm text-err">{error}</p>}
        <button
          onClick={submit}
          className="mt-4 w-full rounded-lg bg-em px-4 py-2.5 font-semibold text-bg transition hover:bg-em-bright"
        >
          Confirmar
        </button>
      </div>
    </div>
  )
}
