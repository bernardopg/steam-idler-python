import { useEffect, useState } from 'react'
import { useBot } from './api'
import { AuthDialog } from './components/AuthDialog'
import { Icon, LogoMark, type IconName } from './components/Icon'
import { Dashboard } from './views/Dashboard'
import { LogsView } from './views/LogsView'
import { ReportView } from './views/ReportView'
import { SettingsView } from './views/SettingsView'

type View = 'dashboard' | 'settings' | 'logs' | 'report'

const NAV: { id: View; label: string; icon: IconName }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
  { id: 'settings', label: 'Configurações', icon: 'settings' },
  { id: 'logs', label: 'Logs', icon: 'logs' },
  { id: 'report', label: 'Relatório', icon: 'report' },
]

export default function App() {
  const [view, setView] = useState<View>('dashboard')
  const [navOpen, setNavOpen] = useState(false)
  const [seenLogId, setSeenLogId] = useState(0)
  const bot = useBot()

  const latestLogId = bot.logs.at(-1)?.id ?? 0
  const unseenLogs = bot.logs.filter((log) => log.id > seenLogId)
  const unseenError = unseenLogs.some((log) => log.level === 'ERROR' || log.level === 'CRITICAL')

  // Logs count as read while the Logs view is open.
  useEffect(() => {
    if (view === 'logs') setSeenLogId(latestLogId)
  }, [view, latestLogId])

  useEffect(() => {
    if (!navOpen) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setNavOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOpen])

  const status = bot.snapshot?.status
  const statusDot =
    status === 'running'
      ? 'bg-em shadow-[0_0_8px_rgba(16,185,129,0.8)]'
      : status === 'error'
        ? 'bg-err'
        : status === 'starting' || status === 'stopping'
          ? 'bg-warn animate-pulse'
          : 'bg-dim'

  function selectView(next: View) {
    setView(next)
    setNavOpen(false)
  }

  return (
    <div className="flex h-dvh bg-bg text-ink">
      {navOpen && (
        <div className="fixed inset-0 z-30 bg-bg/70 backdrop-blur-sm lg:hidden" onClick={() => setNavOpen(false)} aria-hidden="true" />
      )}

      <aside
        id="app-nav"
        className={`fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-edge-soft bg-surface transition-transform duration-200 lg:static lg:translate-x-0 ${
          navOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-3 px-5 py-5">
          <LogoMark />
          <div>
            <p className="text-sm font-bold leading-tight tracking-tight">Steam Idle Bot</p>
            <p className="text-xs text-dim">farm de cartas</p>
          </div>
        </div>
        <nav className="mt-2 flex-1 space-y-1 px-3" aria-label="Seções">
          {NAV.map((item) => {
            const active = view === item.id
            const showDot = item.id === 'logs' && !active && unseenLogs.length > 0
            return (
              <button
                key={item.id}
                onClick={() => selectView(item.id)}
                aria-current={active ? 'page' : undefined}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${
                  active ? 'bg-raised font-semibold text-em-soft' : 'text-mut hover:bg-raised/60 hover:text-ink'
                }`}
              >
                <Icon name={item.icon} />
                {item.label}
                {showDot && (
                  <span
                    className={`ml-auto h-1.5 w-1.5 rounded-full ${unseenError ? 'bg-err' : 'bg-em'}`}
                    aria-label={unseenError ? 'Novos erros' : 'Novas linhas'}
                  />
                )}
              </button>
            )
          })}
        </nav>
        <div className="flex items-center gap-2.5 border-t border-edge-soft px-5 py-4 text-xs text-mut" role="status">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusDot}`} />
          <span className="truncate">
            {bot.connected ? (bot.snapshot?.account ?? 'Steam não conectada') : 'reconectando ao servidor…'}
          </span>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-edge-soft bg-surface px-4 py-3 lg:hidden">
          <button
            onClick={() => setNavOpen(true)}
            className="rounded-lg border border-edge p-2 text-mut"
            aria-label="Abrir menu"
            aria-expanded={navOpen}
            aria-controls="app-nav"
          >
            <Icon name="menu" />
          </button>
          <p className="text-sm font-semibold">{NAV.find((item) => item.id === view)?.label}</p>
        </header>

        {!bot.connected && (
          <div className="border-b border-warn/30 bg-warn/10 px-4 py-2 text-center text-xs font-medium text-warn" role="alert">
            Conexão com o servidor perdida — tentando reconectar…
          </div>
        )}

        <main className="min-w-0 flex-1 overflow-y-auto p-5 lg:p-8">
          {view === 'dashboard' && <Dashboard snapshot={bot.snapshot} connected={bot.connected} />}
          {/* Kept mounted so unsaved edits survive switching views. */}
          <div hidden={view !== 'settings'}>
            <SettingsView running={bot.snapshot?.running ?? false} />
          </div>
          {view === 'logs' && <LogsView logs={bot.logs} onClear={bot.clearLogs} />}
          {view === 'report' && <ReportView report={bot.report} />}
        </main>
      </div>

      {bot.authRequest && <AuthDialog request={bot.authRequest} onDone={bot.dismissAuth} />}
    </div>
  )
}
