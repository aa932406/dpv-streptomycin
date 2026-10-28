'use client'

import { AlertTriangle, FolderSearch } from 'lucide-react'
import { EmptyState } from '@/components/common/layout/EmptyState'

export function PageLoading({ label = '正在分析数据…' }: { label?: string }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="size-3.5 animate-spin rounded-full border-2 border-border border-t-foreground" />
        {label}
      </div>
      <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="min-h-[96px] animate-pulse rounded-[20px] bg-muted" />
        ))}
      </div>
      <div className="h-64 animate-pulse rounded-[20px] bg-muted" />
    </div>
  )
}

export function PageError({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="rounded-[20px] bg-muted">
      <EmptyState icon={AlertTriangle} title={title} description={detail} />
    </div>
  )
}

export function NoCurves() {
  return (
    <div className="rounded-[20px] bg-muted">
      <EmptyState
        icon={FolderSearch}
        title="这个文件夹里没有可用的 DPV 曲线"
        description="换一个数据文件夹，或者在「数据」页检查扫描类型与 QC 门槛。"
      />
    </div>
  )
}
