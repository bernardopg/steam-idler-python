import { useState } from 'react'
import { Icon } from '../components/Icon'

interface ReportViewProps {
  report: string
}

export function ReportView({ report }: ReportViewProps) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(report)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard needs a secure context / permission; the download still works */
    }
  }

  function download() {
    const blob = new Blob([report], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `idle_report_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`
    link.click()
    URL.revokeObjectURL(url)
  }

  if (!report) {
    return <p className="text-dim">Nenhum relatório ainda. Ele aparece aqui ao final de cada sessão.</p>
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-4">
        <button onClick={copy} className="inline-flex items-center gap-1.5 text-sm text-mut transition hover:text-em-soft">
          <Icon name={copied ? 'check' : 'copy'} />
          {copied ? 'Copiado' : 'Copiar relatório'}
        </button>
        <button onClick={download} className="inline-flex items-center gap-1.5 text-sm text-mut transition hover:text-em-soft">
          <Icon name="download" />
          Baixar .txt
        </button>
      </div>
      <pre className="overflow-x-auto rounded-xl border border-edge-soft bg-surface p-5 font-mono text-xs leading-relaxed text-ink">
        {report}
      </pre>
    </div>
  )
}
