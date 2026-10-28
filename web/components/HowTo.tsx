'use client'

import { ChevronDown } from 'lucide-react'

/** 折叠式「怎么读这张图」。每张图都带一个 —— 图是这个应用里最容易被误读的部分。 */
export function HowTo({ title = '怎么读这张图', items }: { title?: string; items: React.ReactNode[] }) {
  return (
    <details className="group mt-3 rounded-2xl bg-background/60 px-3.5 py-3">
      <summary className="flex cursor-pointer select-none list-none items-center justify-between gap-2 text-[11px] font-medium text-foreground">
        {title}
        <ChevronDown className="size-3.5 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <ol className="mt-2 list-decimal space-y-1.5 pl-4 text-[11px] leading-5 text-muted-foreground">
        {items.map((t, i) => <li key={i}>{t}</li>)}
      </ol>
    </details>
  )
}
