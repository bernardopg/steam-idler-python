import { useState } from 'react'
import { useBot } from './api'
import { AuthDialog } from './components/AuthDialog'
import { Dashboard } from './views/Dashboard'
import { LogsView } from './views/LogsView'
import { ReportView } from './views/ReportView'
import { SettingsView } from './views/SettingsView'

type View = 'dashboard' | 'settings' | 'logs' | 'report'

const NAV: { id: View; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '▦' },
  { id: 'settings', label: 'Configurações', icon: '⚙' },
  { id: 'logs', label: 'Logs', icon: '≣' },
  { id: 'report', label: 'Relatório', icon: '☰' },
]

export default function App() {
  const [view, setView] = useState<View>('dashboard')
  const bot = useBot()

  const statusDot =
    bot.snapshot?.status === 'running'
      ? 'bg-em shadow-[0_0_8px_rgba(16,185,129,0.8)]'
      : bot.snapshot?.status === 'error'
        ? 'bg-err'
        : bot.snapshot?.status === 'starting' || bot.snapshot?.status === 'stopping'
          ? 'bg-warn'
          : 'bg-dim'

  return (
    <div className="flex h-screen bg-bg text-ink">
      <aside className="flex w-56 shrink-0 flex-col border-r border-edge-soft bg-surface">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <span className="text-2xl">🎴</span>
          <div>
            <p className="text-sm font-bold leading-tight">Steam Idle Bot</p>
            <p className="text-xs text-dim">card farming</p>
          </div>
        </div>
        <nav className="mt-2 flex-1 space-y-1 px-3">
          {NAV.map((item) => (
            <button
              key={item.id}
              onClick={() => setView(item.id)}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${
                view === item.id ? 'bg-raised font-semibold text-em-soft' : 'text-mut hover:bg-raised/60 hover:text-ink'
              }`}
            >
              <span className="w-4 text-center">{item.icon}</span>
              {item.label}
              {item.id === 'logs' && bot.logs.length > 0 && view !== 'logs' && (
                <span className="ml-auto h-1.5 w-1.5 rounded-full bg-em" />
              )}
            </button>
          ))}
        </nav>
        <div className="flex items-center gap-2.5 border-t border-edge-soft px-5 py-4 text-xs text-mut">
          <span className={`h-2.5 w-2.5 rounded-full ${statusDot}`} />
          {bot.connected ? (bot.snapshot?.account ?? 'desconectado da Steam') : 'reconectando…'}
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto p-8">
        {view === 'dashboard' && <Dashboard snapshot={bot.snapshot} connected={bot.connected} />}
        {view === 'settings' && <SettingsView />}
        {view === 'logs' && <LogsView logs={bot.logs} onClear={bot.clearLogs} />}
        {view === 'report' && <ReportView report={bot.report} />}
      </main>

      {bot.authRequest && <AuthDialog request={bot.authRequest} onDone={bot.dismissAuth} />}
    </div>
  )
}
