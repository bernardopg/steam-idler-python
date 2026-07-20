import { useEffect, useMemo, useRef, useState } from 'react'
import type { LogLine } from '../types'

const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const
type LevelFilter = 'ALL' | (typeof LEVELS)[number]

const levelClass: Record<string, string> = {
  DEBUG: 'text-dim',
  INFO: 'text-mut',
  WARNING: 'text-warn',
  ERROR: 'text-err',
  CRITICAL: 'text-err font-bold',
}

interface LogsViewProps {
  logs: LogLine[]
  onClear: () => void
}

export function LogsView({ logs, onClear }: LogsViewProps) {
  const [autoScroll, setAutoScroll] = useState(true)
  const [copied, setCopied] = useState(false)
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('ALL')
  const [search, setSearch] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return logs.filter(
      (log) => (levelFilter === 'ALL' || log.level === levelFilter) && (needle === '' || log.line.toLowerCase().includes(needle)),
    )
  }, [logs, levelFilter, search])

  useEffect(() => {
    if (autoScroll) endRef.current?.scrollIntoView({ behavior: 'instant', block: 'end' })
  }, [filtered, autoScroll])

  async function copyAll() {
    await navigator.clipboard.writeText(filtered.map((l) => l.line).join('\n'))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex cursor-pointer items-center gap-2 text-mut">
          <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
          Auto-scroll
        </label>
        <div className="flex overflow-hidden rounded-lg border border-edge">
          {(['ALL', ...LEVELS] as LevelFilter[]).map((level) => (
            <button
              key={level}
              onClick={() => setLevelFilter(level)}
              className={`px-2.5 py-1 text-xs font-medium transition ${
                levelFilter === level ? 'bg-raised text-em-soft' : 'text-dim hover:text-mut'
              }`}
            >
              {level}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar nos logs…"
          className="w-44 rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-ink outline-none focus:border-em"
        />
        <button onClick={copyAll} className="text-mut transition hover:text-em-soft">
          {copied ? '✓ Copiado' : 'Copiar'}
        </button>
        <button onClick={onClear} className="text-mut transition hover:text-err">
          Limpar
        </button>
        <span className="tnum ml-auto text-xs text-dim">
          {filtered.length}/{logs.length} linhas
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-edge-soft bg-surface p-4 font-mono text-xs leading-relaxed">
        {logs.length === 0 && <p className="text-dim">Sem logs ainda. Inicie o bot para acompanhar a sessão aqui.</p>}
        {logs.length > 0 && filtered.length === 0 && <p className="text-dim">Nenhuma linha corresponde ao filtro.</p>}
        {filtered.map((log, index) => (
          <p key={index} className={`whitespace-pre-wrap ${levelClass[log.level] ?? 'text-mut'}`}>
            {log.line}
          </p>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}
