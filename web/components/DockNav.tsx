'use client'

import { usePathname } from 'next/navigation'
import {
  Database, LayoutDashboard, LineChart, Table2, Target, Brain, Sparkles, Package,
} from 'lucide-react'
import { FloatingDock, type FloatingDockItem } from '@/components/ui/floating-dock'

type NavItem = {
  href: string
  title: string
  tooltip: string
  icon: typeof Database
  groupKey: string
  groupLabel?: string
}

const ITEMS: NavItem[] = [
  { href: '/data', title: '数据', tooltip: '数据：文件夹、元数据、QC', icon: Database, groupKey: 'in', groupLabel: '输入' },
  { href: '/verdict', title: '结论', tooltip: '结论：有没有、多少浓度', icon: LayoutDashboard, groupKey: 'see', groupLabel: '看结果' },
  { href: '/curves', title: '曲线', tooltip: '曲线：原始与基线校正曲线', icon: LineChart, groupKey: 'see' },
  { href: '/stats', title: '统计', tooltip: '统计：ANOVA、Tukey、PCA', icon: Table2, groupKey: 'see' },
  { href: '/calib', title: '校准', tooltip: '校准：曲线、LOD/LOQ、逐批', icon: Target, groupKey: 'quant', groupLabel: '定量' },
  { href: '/models', title: '建模', tooltip: '建模：留一电极验证、置换检验', icon: Brain, groupKey: 'quant' },
  { href: '/predict', title: '预测', tooltip: '预测：未知样品、模型训练', icon: Sparkles, groupKey: 'quant' },
  { href: '/export', title: '导出', tooltip: '导出：报告包、图表、数据表', icon: Package, groupKey: 'out', groupLabel: '输出' },
]

export function DockNav() {
  const path = usePathname()
  const items: FloatingDockItem[] = ITEMS.map((it) => {
    const Icon = it.icon
    const active = path === it.href
    return {
      title: it.title,
      tooltip: it.tooltip,
      groupKey: it.groupKey,
      groupLabel: it.groupLabel,
      href: it.href,
      icon: (
        <Icon
          className={
            'h-full w-full ' + (active ? 'text-foreground' : 'text-neutral-500 dark:text-neutral-300')
          }
        />
      ),
    }
  })

  return (
    <div className="fixed bottom-5 left-1/2 z-40 -translate-x-1/2 select-none">
      <FloatingDock
        items={items}
        desktopClassName="bg-background/70 backdrop-blur-md border border-border/40 shadow-lg shadow-black/10 dark:shadow-white/5 h-16 pb-3 px-4 gap-2"
        mobileButtonClassName="bg-background/70 backdrop-blur-md border border-border/40 shadow-lg shadow-black/10 dark:shadow-white/5 h-12 w-12"
      />
    </div>
  )
}
