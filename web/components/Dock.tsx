'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Database, LayoutDashboard, LineChart, Table2, Target, Brain, Sparkles, Package } from 'lucide-react'
import { cn } from '@/lib/utils'

const ITEMS = [
  { href: '/data', label: '数据', icon: Database },
  { href: '/verdict', label: '结论', icon: LayoutDashboard },
  { href: '/curves', label: '曲线', icon: LineChart },
  { href: '/stats', label: '统计', icon: Table2 },
  { href: '/calib', label: '校准', icon: Target },
  { href: '/models', label: '建模', icon: Brain },
  { href: '/predict', label: '预测', icon: Sparkles },
  { href: '/export', label: '导出', icon: Package },
]

export function Dock() {
  const path = usePathname()
  return (
    <nav className="fixed bottom-5 left-1/2 z-40 -translate-x-1/2">
      <div className="dock-shadow flex items-center gap-1 rounded-2xl border border-[#e8eaee] bg-white/92 px-2 py-1.5 backdrop-blur">
        {ITEMS.map(({ href, label, icon: Icon }) => {
          const active = path === href
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex w-[62px] flex-col items-center gap-1 rounded-xl px-2 py-1.5 text-[11px] transition',
                active ? 'bg-[#f2f4f7] text-[#101828]' : 'text-[#98a2b3] hover:bg-[#f9fafb] hover:text-[#475467]',
              )}
            >
              <Icon size={17} strokeWidth={active ? 2.2 : 1.8} />
              {label}
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
