import { useState } from 'react'
import { api } from '../api'
import { StatCard } from '../components/StatCard'
import type { Snapshot } from '../types'

const statusLabel: Record<Snapshot['status'], { text: string; tone: 'default' | 'em' | 'warn' | 'err' }> = {
  stopped: { text: 'Parado', tone: 'default' },
  starting: { text: 'Iniciando…', tone: 'warn' },
  running: { text: 'Rodando', tone: 'em' },
  stopping: { text: 'Parando…', tone: 'warn' },
  error: { text: 'Erro', tone: 'err' },
}

function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${Math.round(minutes % 60)}min`
}

interface DashboardProps {
  snapshot: Snapshot | null
  connected: boolean
}

export function Dashboard({ snapshot, connected }: DashboardProps) {
  const [dryRun, setDryRun] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const status = snapshot?.status ?? 'stopped'
  const running = snapshot?.running ?? false
  const info = statusLabel[status]

  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setActionError(null)
    try {
      await action()
    } catch (exc) {
      setActionError(String(exc))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <button
          disabled={busy || running || !connected}
          onClick={() => act(() => api.startBot(dryRun))}
          className="rounded-lg bg-em px-6 py-2.5 font-semibold text-bg transition hover:bg-em-bright disabled:cursor-not-allowed disabled:opacity-40"
        >
          ▶ Iniciar
        </button>
        <button
          disabled={busy || !running}
          onClick={() => act(() => api.stopBot())}
          className="rounded-lg border border-edge px-6 py-2.5 font-semibold text-mut transition hover:border-err hover:text-err disabled:cursor-not-allowed disabled:opacity-40"
        >
          ■ Parar
        </button>
        <label className="ml-1 flex cursor-pointer items-center gap-2 text-sm text-mut">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} disabled={running} />
          Dry run (não conecta à Steam)
        </label>
        {snapshot?.dry_run && running && (
          <span className="rounded-full border border-warn/40 px-3 py-1 text-xs font-medium text-warn">DRY RUN</span>
        )}
        {actionError && <p className="w-full text-sm text-err">{actionError}</p>}
        {snapshot?.last_error && status === 'error' && <p className="w-full text-sm text-err">{snapshot.last_error}</p>}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard label="Status" value={info.text} tone={info.tone} />
        <StatCard label="Conta" value={snapshot?.account ?? '—'} />
        <StatCard label="Sessão" value={formatMinutes(snapshot?.session_minutes ?? 0)} tone="em" />
        <StatCard label="Jogos em idle" value={String(snapshot?.games_count ?? 0)} />
        <StatCard
          label="Drops na sessão"
          value={String(snapshot?.session_drops ?? 0)}
          tone={snapshot?.session_drops ? 'em' : 'default'}
        />
      </div>

      <div className="overflow-hidden rounded-xl border border-edge-soft">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-edge-soft bg-surface text-left text-xs uppercase tracking-widest text-dim">
              <th className="px-4 py-3 font-medium">App ID</th>
              <th className="px-4 py-3 font-medium">Jogo</th>
              <th className="px-4 py-3 text-right font-medium">Cartas restantes</th>
              <th className="px-4 py-3 text-right font-medium">Drops</th>
              <th className="px-4 py-3 text-right font-medium">Tempo idle</th>
            </tr>
          </thead>
          <tbody>
            {(snapshot?.games ?? []).map((game) => (
              <tr key={game.app_id} className="border-b border-edge-soft/50 transition hover:bg-raised">
                <td className="tnum px-4 py-2.5 font-mono text-mut">{game.app_id}</td>
                <td className="max-w-md truncate px-4 py-2.5">{game.name}</td>
                <td className="tnum px-4 py-2.5 text-right text-em-soft">{game.cards_remaining ?? '?'}</td>
                <td className="tnum px-4 py-2.5 text-right">{game.drops || '—'}</td>
                <td className="tnum px-4 py-2.5 text-right text-mut">{formatMinutes(game.idle_minutes)}</td>
              </tr>
            ))}
            {(snapshot?.games ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-dim">
                  {running ? 'Selecionando jogos…' : 'Nenhum jogo em idle. Inicie o bot para começar.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {snapshot?.cards_remaining_known != null && (
        <p className="text-sm text-mut">
          Cartas restantes conhecidas: <span className="tnum font-semibold text-em-soft">{snapshot.cards_remaining_known}</span>
        </p>
      )}
    </div>
  )
}
