'use client'

/** 全站统一的卡片：rounded-[20px] bg-muted，无边框、靠底色区分（对齐 workbuddy 的卡片写法）。 */
export function Panel({ title, sub, actions, children, className }: {
  title?: string
  sub?: string
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={'rounded-[20px] bg-muted p-4 ' + (className || '')}>
      {(title || actions) ? (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-baseline gap-2">
            {title ? <h2 className="text-sm font-medium">{title}</h2> : null}
            {sub ? <span className="text-[11px] text-muted-foreground">{sub}</span> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  )
}
