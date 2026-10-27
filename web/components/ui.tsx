'use client'

import { cn } from '@/lib/utils'

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn('card', className)}>{children}</div>
}

export function CardBody({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn('px-5 py-4', className)}>{children}</div>
}

export function SectionTitle({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div className="mb-2.5 flex items-baseline gap-2">
      <h3 className="text-[14px] font-semibold text-[#101828]">{children}</h3>
      {sub ? <span className="text-[12px] text-[#98a2b3]">{sub}</span> : null}
    </div>
  )
}

export function StatCard({
  label, value, sub, icon,
}: { label: string; value: React.ReactNode; sub?: string; icon?: React.ReactNode }) {
  return (
    <Card className="px-5 py-4">
      <div className="flex items-start justify-between">
        <span className="text-[12.5px] text-[#667085]">{label}</span>
        {icon ? <span className="text-[#c3c8d1]">{icon}</span> : null}
      </div>
      <div className="mt-1.5 break-words text-[24px] font-semibold leading-tight tracking-tight text-[#101828] tnum">{value}</div>
      {sub ? <div className="mt-2 text-[12px] text-[#98a2b3]">{sub}</div> : null}
    </Card>
  )
}

const TONES = {
  ok: 'bg-[#ecfdf3] text-[#067647] ring-[#abefc6]',
  bad: 'bg-[#fef3f2] text-[#b42318] ring-[#fecdca]',
  warn: 'bg-[#fffaeb] text-[#b54708] ring-[#fedf89]',
  mute: 'bg-[#f2f4f7] text-[#475467] ring-[#e4e7ec]',
  info: 'bg-[#eff8ff] text-[#175cd3] ring-[#b2ddff]',
}

export function Badge({ tone = 'mute', children }: { tone?: keyof typeof TONES; children: React.ReactNode }) {
  return (
    <span className={cn('inline-flex shrink-0 items-center whitespace-nowrap rounded-md px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset', TONES[tone])}>
      {children}
    </span>
  )
}

export function Note({
  tone = 'info', title, children,
}: { tone?: 'info' | 'warn' | 'bad' | 'ok' | 'mute'; title?: string; children?: React.ReactNode }) {
  const map = {
    mute: 'bg-[#f9fafb] border-[#eaecf0] text-[#475467]',
    info: 'bg-[#eff8ff] border-[#b2ddff] text-[#175cd3]',
    warn: 'bg-[#fffaeb] border-[#fedf89] text-[#b54708]',
    bad: 'bg-[#fef3f2] border-[#fecdca] text-[#b42318]',
    ok: 'bg-[#ecfdf3] border-[#abefc6] text-[#067647]',
  } as const
  return (
    <div className={cn('rounded-xl border px-3.5 py-2.5 text-[12.5px] leading-relaxed', map[tone])}>
      {title ? <div className="font-semibold">{title}</div> : null}
      {children ? <div className={title ? 'mt-1' : ''}>{children}</div> : null}
    </div>
  )
}

export function KeyVal({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <span className="text-[12.5px] text-[#667085]">{k}</span>
      <span className="text-[12.5px] font-medium text-[#101828] tnum">{v}</span>
    </div>
  )
}

export function Table({ head, children, className }: { head: React.ReactNode[]; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="w-full border-collapse text-[12.5px]">
        <thead>
          <tr className="border-b border-[#eaecf0] text-left text-[11.5px] font-medium text-[#667085]">
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-[#101828]">{children}</tbody>
      </table>
    </div>
  )
}

export function Td({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <td className={cn('whitespace-nowrap px-3 py-2 align-middle tnum', className)}>{children}</td>
}

export function Loading() {
  return (
    <div className="flex items-center gap-2 py-16 text-[13px] text-[#98a2b3]">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[#d0d5dd] border-t-transparent" />
      正在分析数据…
    </div>
  )
}


/** Collapsible "how to read this chart" block. The charts in this app are the
 *  part users struggle with most, so every scatter/plot carries one. */
export function HowTo({ title = '怎么读这张图', items }: { title?: string; items: React.ReactNode[] }) {
  return (
    <details className="mt-3 rounded-xl border border-[#eef0f3] bg-[#fbfcfd] px-3.5 py-2.5">
      <summary className="cursor-pointer select-none text-[12.5px] font-medium text-[#344054]">
        {title}
      </summary>
      <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-[12.5px] leading-relaxed text-[#475467]">
        {items.map((t, i) => <li key={i}>{t}</li>)}
      </ol>
    </details>
  )
}
