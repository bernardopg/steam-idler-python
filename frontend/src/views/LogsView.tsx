import { useEffect, useRef, useState } from 'react'
import type { LogLine } from '../types'

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
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll) endRef.current?.scrollIntoView({ behavior: 'instant', block: 'end' })
  }, [logs, autoScroll])

  async function copyAll() {
    await navigator.clipboard.writeText(logs.map((l) => l.line).join('\n'))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center gap-4 text-sm">
        <label className="flex cursor-pointer items-center gap-2 text-mut">
          <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
          Auto-scroll
        </label>
        <button onClick={copyAll} className="text-mut transition hover:text-em-soft">
          {copied ? '✓ Copiado' : 'Copiar'}
        </button>
        <button onClick={onClear} className="text-mut transition hover:text-err">
          Limpar
        </button>
        <span className="tnum ml-auto text-xs text-dim">{logs.length} linhas</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-edge-soft bg-surface p-4 font-mono text-xs leading-relaxed">
        {logs.length === 0 && <p className="text-dim">Sem logs ainda. Inicie o bot para acompanhar a sessão aqui.</p>}
        {logs.map((log, index) => (
          <p key={index} className={`whitespace-pre-wrap ${levelClass[log.level] ?? 'text-mut'}`}>
            {log.line}
          </p>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}
