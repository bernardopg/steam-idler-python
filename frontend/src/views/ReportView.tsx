import { useState } from 'react'

interface ReportViewProps {
  report: string
}

export function ReportView({ report }: ReportViewProps) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(report)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (!report) {
    return <p className="text-dim">Nenhum relatório ainda. Ele aparece aqui ao final de cada sessão.</p>
  }

  return (
    <div className="space-y-3">
      <button onClick={copy} className="text-sm text-mut transition hover:text-em-soft">
        {copied ? '✓ Copiado' : 'Copiar relatório'}
      </button>
      <pre className="overflow-x-auto rounded-xl border border-edge-soft bg-surface p-5 font-mono text-xs leading-relaxed text-ink">
        {report}
      </pre>
    </div>
  )
}
