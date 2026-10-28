'use client'

import { useEffect, useState } from 'react'
import { Download, FlaskConical, Moon, SlidersHorizontal, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useFolder } from '@/lib/folder-context'
import { reportUrl } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

const TECH_CN: Record<string, string> = {
  DPV: '差分脉冲伏安 (DPV)',
  'DPV-stripping': '差分脉冲溶出伏安',
  SWV: '方波伏安 (SWV)',
  'SWV-stripping': '方波溶出伏安',
  CV: '循环伏安 (CV)',
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  if (!mounted) {
    return <div className="h-9 w-9 rounded-full bg-muted" aria-hidden />
  }
  const dark = resolvedTheme === 'dark'
  return (
    <Button
      variant="outline"
      size="icon"
      className="rounded-full"
      title={dark ? '切换到浅色' : '切换到深色'}
      aria-label={dark ? '切换到浅色' : '切换到深色'}
      onClick={() => setTheme(dark ? 'light' : 'dark')}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  )
}

export function ControlBar() {
  const { folders, folder, setFolder, order, refFrac, technique, setParams, data, loading } = useFolder()
  const techOpts = data?.meta?.technique_options || []

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2.5">
        <div className="grid size-8 place-items-center rounded-xl bg-primary text-primary-foreground">
          <FlaskConical className="size-4" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-[-0.01em]">链霉素 DPV 检测平台</div>
          <div className="text-[11px] text-muted-foreground">差分脉冲伏安 · 定性筛查与定量</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select value={folder || undefined} onValueChange={setFolder}>
          <SelectTrigger className="h-9 w-[240px] rounded-full" aria-label="数据文件夹">
            <SelectValue placeholder={loading ? '正在读取文件夹…' : '选择文件夹'} />
          </SelectTrigger>
          <SelectContent className="max-h-[60vh]">
            {folders.map((f) => (
              <SelectItem key={f.id} value={f.id}>
                {f.label}
                {f.is_demo ? '（演示）' : ''} · {f.n_files} 个文件
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="rounded-full">
              <SlidersHorizontal />
              分析参数
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-[320px] rounded-2xl p-4">
            <div className="space-y-4">
              <div>
                <div className="flex items-baseline justify-between">
                  <label className="text-xs text-muted-foreground">基线拟合阶数</label>
                  <span className="text-xs font-medium tabular-nums">{order}</span>
                </div>
                <input
                  type="range" min={2} max={6} step={1} value={order}
                  onChange={(e) => setParams({ order: Number(e.target.value) })}
                  className="mt-2 w-full accent-foreground"
                />
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                  阶数越高，扣掉的基线越弯；峰会被压扁时把它调小。
                </p>
              </div>

              <div>
                <div className="flex items-baseline justify-between">
                  <label className="text-xs text-muted-foreground">内参峰 QC 下限</label>
                  <span className="text-xs font-medium tabular-nums">{Math.round(refFrac * 100)}%</span>
                </div>
                <input
                  type="range" min={0} max={1} step={0.05} value={refFrac}
                  onChange={(e) => setParams({ refFrac: Number(e.target.value) })}
                  className="mt-2 w-full accent-foreground"
                />
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                  低于本批中位数这个比例的曲线会被 QC 剔除。调低保留更多，噪声也更多。
                </p>
              </div>

              <div>
                <label className="text-xs text-muted-foreground">扫描类型</label>
                <Select value={technique} onValueChange={(v) => setParams({ technique: v })}>
                  <SelectTrigger className="mt-1.5 h-9 w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">
                      自动{data?.meta?.technique_cn ? '（' + data.meta.technique_cn + '）' : ''}
                    </SelectItem>
                    {techOpts.map((t) => (
                      <SelectItem key={t} value={t}>{TECH_CN[t] || t}</SelectItem>
                    ))}
                    <SelectItem value="all">全部混在一起（仅看形状）</SelectItem>
                  </SelectContent>
                </Select>
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                  一个文件夹里混了 CV 或溶出伏安时，默认只分析占多数的那种脉冲扫描 ——
                  不同扫描方式的峰电流不在一个量纲上。
                </p>
              </div>
            </div>
          </PopoverContent>
        </Popover>

        <ThemeToggle />

        <Button asChild size="sm" className="rounded-full" disabled={!data}>
          <a
            href={data ? reportUrl(folder, order, refFrac, technique) : '#'}
            aria-disabled={!data}
          >
            <Download />
            导出报告
          </a>
        </Button>
      </div>
    </div>
  )
}
