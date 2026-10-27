import { type FormEvent, useState } from 'react'
import { api, errorMessage } from '../api'
import { Icon } from '../components/Icon'
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

function parseAppIds(raw: string): number[] | null {
  const parts = raw.split(/[\s,;]+/).filter(Boolean)
  const ids = parts.map(Number)
  return parts.length > 0 && ids.every((id) => Number.isInteger(id) && id > 0) ? ids : null
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
  const stopping = status === 'stopping'
  const info = statusLabel[status]
  const games = snapshot?.games ?? []

  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setActionError(null)
    try {
      await action()
    } catch (exc) {
      setActionError(errorMessage(exc))
    } finally {
      setBusy(false)
    }
  }

  function requestStop() {
    const question = stopping
      ? 'Forçar a parada? A verificação final das cartas será pulada.'
      : 'Parar o bot agora? O idle em andamento será interrompido e o relatório gerado.'
    if (window.confirm(question)) void act(() => api.stopBot())
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <button
          disabled={busy || running || !connected}
          onClick={() => act(() => api.startBot(dryRun))}
          className="inline-flex items-center gap-2 rounded-lg bg-em px-6 py-2.5 font-semibold text-bg transition hover:bg-em-bright disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Icon name="play" />
          Iniciar
        </button>
        <button
          disabled={busy || !running}
          onClick={requestStop}
          className="inline-flex items-center gap-2 rounded-lg border border-edge px-6 py-2.5 font-semibold text-mut transition hover:border-err hover:text-err disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Icon name="stop" />
          {stopping ? 'Forçar parada' : 'Parar'}
        </button>
        <label className="ml-1 flex cursor-pointer items-center gap-2 text-sm text-mut">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} disabled={running} />
          Dry run <span className="text-dim">(só mostra a configuração, sem conectar à Steam)</span>
        </label>
        {snapshot?.dry_run && running && (
          <span className="rounded-full border border-warn/40 px-3 py-1 text-xs font-medium text-warn">DRY RUN</span>
        )}
      </div>

      {(actionError || (snapshot?.last_error && status === 'error')) && (
        <div className="rounded-lg border border-err/40 bg-err/10 px-4 py-3 text-sm text-err" role="alert">
          {actionError ?? snapshot?.last_error}
        </div>
      )}

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

      <div className="overflow-x-auto rounded-xl border border-edge-soft">
        <table className="w-full min-w-[640px] text-sm">
          <caption className="sr-only">Jogos em idle nesta sessão</caption>
          <thead>
            <tr className="border-b border-edge-soft bg-surface text-left text-xs uppercase tracking-widest text-dim">
              <th scope="col" className="px-4 py-3 font-medium">App ID</th>
              <th scope="col" className="px-4 py-3 font-medium">Jogo</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Cartas restantes</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Drops</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Tempo idle</th>
            </tr>
          </thead>
          <tbody>
            {games.map((game) => (
              <tr key={game.app_id} className="border-b border-edge-soft/50 transition hover:bg-raised">
                <td className="tnum px-4 py-2.5 font-mono text-mut">{game.app_id}</td>
                <td className="max-w-md truncate px-4 py-2.5" title={game.name}>
                  {game.name}
                </td>
                <td className="tnum px-4 py-2.5 text-right text-em-soft" title={game.cards_remaining == null ? 'Contagem ainda desconhecida' : undefined}>
                  {game.cards_remaining ?? '?'}
                </td>
                <td className="tnum px-4 py-2.5 text-right">{game.drops ? `+${game.drops}` : '—'}</td>
                <td className="tnum px-4 py-2.5 text-right text-mut">{formatMinutes(game.idle_minutes)}</td>
              </tr>
            ))}
            {games.length === 0 && (
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

      <StopAppIdsPanel disabled={running || !connected} />
    </div>
  )
}

/** Maintenance: stop leftover steam-utility idle processes (same as --stop-app-ids). */
function StopAppIdsPanel({ disabled }: { disabled: boolean }) {
  const [raw, setRaw] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  const appIds = parseAppIds(raw)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!appIds) return
    setBusy(true)
    setResult(null)
    try {
      const { status } = await api.stopAppIds(appIds)
      setResult({
        tone: 'ok',
        text: status ? `${status} processo(s) encerrado(s).` : 'Nenhum idle do steam-utility rodando para esses App IDs.',
      })
    } catch (exc) {
      setResult({ tone: 'err', text: errorMessage(exc) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="group rounded-xl border border-edge-soft bg-surface">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-4 text-sm font-semibold text-mut hover:text-ink">
        <Icon name="wrench" />
        Manutenção: parar idles do steam-utility
        <span className="ml-auto text-xs font-normal text-dim group-open:hidden">expandir</span>
      </summary>
      <form onSubmit={submit} className="space-y-3 border-t border-edge-soft px-5 py-4">
        <p className="text-sm text-dim">
          Encerra processos <code className="font-mono text-mut">steam-utility idle</code> que ficaram rodando de sessões anteriores.
          Disponível só com o bot parado.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <label className="sr-only" htmlFor="stop-app-ids">
            App IDs
          </label>
          <input
            id="stop-app-ids"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder="570, 730"
            inputMode="numeric"
            disabled={disabled || busy}
            className="w-56 rounded-lg border border-edge bg-raised px-3 py-2 font-mono text-sm text-ink outline-none transition placeholder:text-dim focus:border-em disabled:opacity-40"
          />
          <button
            type="submit"
            disabled={disabled || busy || !appIds}
            className="rounded-lg border border-edge px-4 py-2 text-sm font-semibold text-mut transition hover:border-err hover:text-err disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? 'Parando…' : 'Parar processos'}
          </button>
          {raw.trim() !== '' && !appIds && <span className="text-xs text-err">Use números separados por vírgula.</span>}
        </div>
        {result && (
          <p className={`text-sm ${result.tone === 'ok' ? 'text-em-bright' : 'text-err'}`} role="status">
            {result.text}
          </p>
        )}
      </form>
    </details>
  )
}
