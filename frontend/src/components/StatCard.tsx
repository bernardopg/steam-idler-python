interface StatCardProps {
  label: string
  value: string
  tone?: 'default' | 'em' | 'warn' | 'err'
  hint?: string
}

const toneClass: Record<NonNullable<StatCardProps['tone']>, string> = {
  default: 'text-ink',
  em: 'text-em-bright',
  warn: 'text-warn',
  err: 'text-err',
}

export function StatCard({ label, value, tone = 'default', hint }: StatCardProps) {
  return (
    <div className="rounded-xl border border-edge-soft bg-surface px-5 py-4">
      <p className="text-xs font-medium uppercase tracking-widest text-dim">{label}</p>
      <p className={`tnum mt-1.5 truncate text-2xl font-semibold ${toneClass[tone]}`} title={hint}>
        {value}
      </p>
    </div>
  )
}
