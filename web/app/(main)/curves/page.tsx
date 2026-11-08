'use client'

import { useMemo, useState } from 'react'
import { useFolder } from '@/lib/folder-context'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader } from '@/components/common/layout/PageHeader'
import { CurvesChart, Legend, RatioScatter } from '@/components/charts'
import { HowTo } from '@/components/HowTo'
import { Panel } from '@/components/Panel'
import { NoCurves, PageError, PageLoading } from '@/components/PageState'
import { fmtNum } from '@/lib/utils'

export default function CurvesPage() {
  const { data, loading, error } = useFolder()
  const [showBand, setShowBand] = useState(false)
  const [sel, setSel] = useState<string>('')

  const raw = data?.curves?.raw || []
  const files = useMemo(() => raw.map((r) => r.file), [raw])
  const active = sel && files.includes(sel) ? sel : files[0] || ''
  const one = raw.find((r) => r.file === active)
  const groupColor = (g: string) => data?.curves.series.find((s) => s.name === g)?.color || '#2e90fa'

  if (loading) return <PageLoading />
  if (error) return <PageError title="后端没有响应" detail={error} />
  if (!data || !data.meta?.n_curves) return <NoCurves />

  const m = data.meta
  const scatter = data.samples
    .filter((s) => (s.I_MB ?? 0) > 0 && (s.I_ref ?? 0) > 0)
    .map((s) => ({ file: s.file, group: s.group, I_MB: s.I_MB as number, I_ref: s.I_ref as number, color: groupColor(s.group) }))

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <PageHeader
        title="曲线"
        description={`基线校正后的 DPV 曲线 · ${m.n_curves} 条 · ${m.n_points} 点 · 窗口 ${m.window[1].toFixed(2)} → ${m.window[0].toFixed(2)} V`}
      />

      <Panel
        title="各条件平均曲线 ± SD"
        sub="基线校正后的响应信号，单位 µA；峰向上为正"
        actions={
          <div className="flex items-center gap-2">
            <Label htmlFor="sd-band" className="text-[11px] font-normal text-muted-foreground">显示 SD 带</Label>
            <Switch id="sd-band" checked={showBand} onCheckedChange={setShowBand} />
          </div>
        }
      >
        <div className="mb-2"><Legend series={data.curves.series} /></div>
        <CurvesChart grid={data.curves.grid} series={data.curves.series} showBand={showBand} height={340} />
        <HowTo title="怎么读这张曲线图" items={[
          <>横轴是电位 E（V），从左到右是扫描方向（正电位 → 负电位）。纵轴是<b>基线校正后</b>的电流（µA），峰向上为正。</>,
          <>MB 峰在 <b>−0.34 V</b> 附近，内参峰（Au@SH-MIL-101(Fe) 的 Fe(III)/Fe(II)）在 <b>+0.35 V</b> 附近。两条线之间的峰高比就是响应指标。</>,
          <>曲线越往上、峰越高 = 该条件下 MB 在电极上的量越多。四条曲线重合说明条件之间没有差别；分开说明有差别。</>,
          <>每组只有 2 条曲线时，均值的 SD 很大，打开「显示 SD 带」会糊成一片 —— 所以默认关闭。</>,
        ]} />
      </Panel>

      <Panel title="MB 峰电流 vs 内参峰电流" sub="每个点是一条曲线，横轴内参峰、纵轴 MB 峰，双对数坐标">
        <RatioScatter height={330} points={scatter} />
        <HowTo title="怎么读这张散点图（最容易被误解的一张）" items={[
          <><b>每个点 = 一条曲线</b>，不是一次测量里的多个数据点。横轴是内参峰 I_ref（Au@SH-MIL-101(Fe) 的 Fe 峰），纵轴是 MB 峰 I_MB。</>,
          <>为什么要这么画：电极面积、涂膜厚度、电极间差异会<b>同时</b>抬高或压低两个峰。只看 I_MB，你分不清「MB 变多了」和「这支电极本来电流就大」。把两个峰放在一起，这种整体漂移会沿着 <b>I_MB = I_ref 的对角线</b>滑动，不改变点的位置方向。</>,
          <>真正有意义的移动是<b>离开对角线</b>：点在角平分线以上 = MB 相对内参偏高（信号开），在以下 = 偏低（信号关）。图中灰色实线是 I_MB = I_ref，虚线是 0.25 / 0.5 / 2 / 4 倍的等比值线。</>,
          <>同一组挤在一个小区域 = 重复性好；同组散得很开 = 组内差异大于组间差异，这时候比组均值没有意义（这正是这批数据的问题：空白组 CV 38–51%）。</>,
          <>两个点完全重合、或被画在边界上 = 该曲线的某个峰读不到（窗口没覆盖或峰太小），去「数据」页看 QC 列。</>,
        ]} />
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Panel className="lg:col-span-2" title="逐条查看" sub="单条曲线的原始读数">
          <Select value={active || undefined} onValueChange={setSel}>
            <SelectTrigger className="h-9 w-full">
              <SelectValue placeholder="选择文件" />
            </SelectTrigger>
            <SelectContent className="max-h-[50vh]">
              {files.map((f) => <SelectItem key={f} value={f}>{f}</SelectItem>)}
            </SelectContent>
          </Select>
          {one ? (
            <>
              <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="h-[3px] w-4 rounded-full" style={{ background: groupColor(one.group) }} />
                {one.group}
              </div>
              <CurvesChart
                grid={data.curves.grid}
                series={[{ name: one.group, mean: one.y, sd: null, n: 1, color: groupColor(one.group) }]}
                height={230}
              />
            </>
          ) : null}
        </Panel>

        <Panel className="lg:col-span-3" title="数据表" sub="按文件列出每条曲线的读数">
          <div className="max-h-[420px] overflow-auto scroll-slim rounded-2xl bg-background/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>文件</TableHead>
                  <TableHead>分组</TableHead>
                  <TableHead>响应</TableHead>
                  <TableHead>I_MB</TableHead>
                  <TableHead>I_ref</TableHead>
                  <TableHead>QC</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.samples.map((s) => (
                  <TableRow key={s.file}>
                    <TableCell className="max-w-[220px] truncate text-muted-foreground">{s.file}</TableCell>
                    <TableCell>
                      <span className="flex items-center gap-1.5">
                        <span className="size-2 rounded-full" style={{ background: groupColor(s.group) }} />
                        {s.group}
                      </span>
                    </TableCell>
                    <TableCell className="tabular-nums">{fmtNum(s.value, 3)}</TableCell>
                    <TableCell className="tabular-nums">{fmtNum(s.I_MB, 2)}</TableCell>
                    <TableCell className="tabular-nums">{fmtNum(s.I_ref, 2)}</TableCell>
                    <TableCell>
                      {s.qc_pass
                        ? <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">通过</Badge>
                        : <Badge variant="secondary">剔除</Badge>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Panel>
      </div>
    </div>
  )
}
