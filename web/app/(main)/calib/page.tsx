'use client'

import Link from 'next/link'
import { AlertTriangle, Beaker, Layers, Ruler, Target } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader } from '@/components/common/layout/PageHeader'
import { StatCard } from '@/components/common/layout/StatCard'
import { CalibChart } from '@/components/charts'
import { HowTo } from '@/components/HowTo'
import { Panel } from '@/components/Panel'
import { NoCurves, PageError, PageLoading } from '@/components/PageState'
import { explainFitError, fmtConc, fmtNum } from '@/lib/utils'

function VerdictBadge({ v }: { v: 'positive' | 'negative' | 'unknown' }) {
  if (v === 'positive') {
    return <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">检出</Badge>
  }
  if (v === 'negative') return <Badge variant="secondary">未检出</Badge>
  return <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">无法判定</Badge>
}

export default function CalibPage() {
  const { data, loading, error } = useFolder()
  if (loading) return <PageLoading />
  if (error) return <PageError title="后端没有响应" detail={error} />
  if (!data || !data.meta?.n_curves) return <NoCurves />

  const fit = data.fit || {}
  const pts = data.calib_points || []
  const verdicts = data.verdicts || []
  const fb = data.fit_batch
  const perBatch = !!fb && !fb.error && (fb.batches?.length || 0) > 1

  const header = (
    <PageHeader
      title="校准与定量"
      description="峰电流对 log10(浓度) 的线性回归 · LOD / LOQ 由空白 3σ 反算"
      actions={
        <>
          <Button variant="outline" size="sm" className="rounded-full" asChild>
            <Link href="/data">核对浓度</Link>
          </Button>
          <Button variant="outline" size="sm" className="rounded-full" asChild>
            <Link href="/verdict">看结论</Link>
          </Button>
        </>
      }
    />
  )

  if (perBatch) {
    const rows = fb!.batches || []
    const lods = rows.map((b) => b.LOD_M).filter((v): v is number => v != null && v > 0)
    const span = lods.length > 1 ? Math.max(...lods) / Math.min(...lods) : 1
    return (
      <div className="flex flex-col gap-4 md:gap-6">
        {header}
        <section className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
          <StatCard label="合并 R²" value={fmtNum(fb!.r2, 3)} hint="各批内部拟合" icon={Target} />
          <StatCard label="全局单线 R²" value={fmtNum(fb!.pooled_r2, 3)} hint="把各批当一批拟合" icon={Ruler} tone="warning" delay={0.04} />
          <StatCard label="留一批次误差" value={fmtNum(fb!.rmse_log_lobo, 2) + ' dex'} hint="换批次后差几个数量级" icon={Layers} tone="info" delay={0.08} />
          <StatCard label="批次" value={rows.length} hint="每批自己的截距" icon={Beaker} delay={0.12} />
        </section>

        <div className="rounded-[20px] bg-blue-500/10 px-4 py-3.5 ring-1 ring-blue-500/20">
          <div className="text-xs font-medium text-blue-700 dark:text-blue-300">这批数据跨多个批次，已自动按批标定</div>
          <p className="mt-1 text-[11px] leading-5 text-blue-700/80 dark:text-blue-300/80">
            每个批次用自己那天的标准点定截距，所有批共用一条斜率 —— 批次之间通常只是整体平移。
            合并 R² 与全局单线 R² 差得越多，说明批次效应越大，越不能拿一条线通吃。
          </p>
        </div>

        <Panel title="各批次校准" sub="每批用自己那天的标准点定截距，斜率共用">
          <div className="overflow-hidden rounded-2xl bg-background/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>批次</TableHead>
                  <TableHead>标准点</TableHead>
                  <TableHead>浓度数</TableHead>
                  <TableHead>截距 a</TableHead>
                  <TableHead>斜率 b</TableHead>
                  <TableHead>R²</TableHead>
                  <TableHead>LOD</TableHead>
                  <TableHead>LOQ</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((b) => (
                  <TableRow key={b.batch}>
                    <TableCell className="font-medium">{b.batch}</TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">{b.n ?? '—'}</TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">{b.levels ?? '—'}</TableCell>
                    <TableCell className="tabular-nums">{fmtNum(b.a, 3)}</TableCell>
                    <TableCell className="tabular-nums">{fmtNum(b.b, 3)}</TableCell>
                    <TableCell className="tabular-nums">{fmtNum(b.r2, 3)}</TableCell>
                    <TableCell className="tabular-nums">{b.LOD_M != null ? fmtConc(b.LOD_M) : (b.note || '—')}</TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">{b.LOQ_M != null ? fmtConc(b.LOQ_M) : '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {span > 5 ? (
            <p className="mt-2 text-[11px] text-muted-foreground">
              各批 LOD 相差 {span.toFixed(0)} 倍 —— 空白噪声不一样，不是 bug。同一批里的样品只能跟自己那批的 LOD 比。
            </p>
          ) : null}
        </Panel>

        {fit.r2 != null ? (
          <Panel title="全局单线对照（不该用）" sub="如果强行把各批当一批拟合，就是这个样子">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MiniKV label="全局 R²" value={fmtNum(fit.r2, 3)} />
              <MiniKV label="全局斜率" value={fmtNum(fit.b, 3)} />
              <MiniKV label="按批合并 R²" value={fmtNum(fb!.r2, 3)} />
              <MiniKV label="差值" value={fmtNum((fb!.r2 ?? 0) - (fit.r2 ?? 0), 3)} />
            </div>
            <div className="mt-3"><CalibChart points={pts} a={fit.a} b={fit.b} /></div>
          </Panel>
        ) : null}

        <Panel title="样品浓度" sub="浓度列留空的行被当作未知样品；浓度用自己那一批的截距算">
          {verdicts.length ? (
            <div className="overflow-hidden rounded-2xl bg-background/60">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>文件</TableHead>
                    <TableHead>批次</TableHead>
                    <TableHead>分组</TableHead>
                    <TableHead>响应</TableHead>
                    <TableHead>判定</TableHead>
                    <TableHead>浓度</TableHead>
                    <TableHead>95% 区间</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {verdicts.map((v) => (
                    <TableRow key={v.file}>
                      <TableCell className="max-w-[220px] truncate text-muted-foreground">{v.file}</TableCell>
                      <TableCell className="text-muted-foreground">{v.batch || '—'}</TableCell>
                      <TableCell className="text-muted-foreground">{v.group}</TableCell>
                      <TableCell className="tabular-nums">{fmtNum(v.value, 3)}</TableCell>
                      <TableCell><VerdictBadge v={v.verdict} /></TableCell>
                      <TableCell className="font-medium tabular-nums">{v.verdict === 'positive' ? (v.C_text || fmtConc(v.C)) : '—'}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{v.C_lo != null ? fmtConc(v.C_lo) + ' ~ ' + fmtConc(v.C_hi) : '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : <p className="text-xs text-muted-foreground">没有未知样品（浓度列全部填了值）。</p>}
        </Panel>
      </div>
    )
  }

  if (fit.error) {
    return (
      <div className="flex flex-col gap-4 md:gap-6">
        {header}
        <div className="flex items-start gap-2.5 rounded-[20px] bg-amber-500/10 px-4 py-3.5 ring-1 ring-amber-500/20">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
          <div className="min-w-0 space-y-1.5">
            <div className="text-xs font-medium">这批数据算不出浓度</div>
            <p className="text-[11px] leading-5 text-muted-foreground">{explainFitError(fit.error)}</p>
            <p className="text-[11px] leading-5 text-muted-foreground">
              要算出浓度，至少需要 3 个浓度水平、每水平 3 支独立电极、外加 3 支空白。缺的是实验设计，不是算法。
            </p>
            <p className="text-[10px] text-muted-foreground/70">后端原文：{fit.error}</p>
          </div>
        </div>
        <Panel title="缺什么" sub="把浓度填进数据表后，这里会画出校准曲线">
          <ul className="space-y-1.5 text-[11px] leading-5 text-muted-foreground">
            <li>· 标准点（已知浓度）：<b className="text-foreground">≥ 3 个浓度</b>，建议 10 pM / 100 pM / 1 nM / 10 nM / 100 nM / 1 µM</li>
            <li>· 空白（浓度填 0）：<b className="text-foreground">≥ 3 条</b>，用来算 LOD</li>
            <li>· 每水平独立电极：<b className="text-foreground">≥ 3 支</b>（同一支电极重复扫描不算）</li>
            <li>· 未知样品：浓度列<b className="text-foreground">留空</b>，工具会自动给出浓度和 95% 区间</li>
          </ul>
        </Panel>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      {header}
      <section className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
        <StatCard label="校准 R²" value={fmtNum(fit.r2, 3)} hint={'标准点 ' + (fit.n_std ?? pts.length)} icon={Target} tone={fit.r2 != null && fit.r2 > 0.99 ? 'success' : 'neutral'} />
        <StatCard label="斜率" value={fmtNum(fit.b, 3)} hint="每十倍浓度" icon={Ruler} delay={0.04} />
        <StatCard label="LOD" value={fit.LOD_M != null ? fmtConc(fit.LOD_M) : '—'} hint="3σ / 斜率" icon={Beaker} tone="info" delay={0.08} />
        <StatCard label="LOQ" value={fit.LOQ_M != null ? fmtConc(fit.LOQ_M) : '—'} hint="10σ / 斜率" icon={Layers} delay={0.12} />
      </section>

      <Panel title="校准曲线" sub={fit.direction === 'signal-off' ? '浓度越高信号越低' : '浓度越高信号越高'}>
        <CalibChart points={pts} a={fit.a} b={fit.b} />
        <HowTo title="怎么读这张校准图" items={[
          <>横轴是 log10(浓度)，纵轴是响应指标（信号比或峰电流）。<b>直线</b>说明响应与浓度的对数成正比，这是定量传感器的前提。</>,
          <>虚线是拟合线，点离线越远残差越大。R² &gt; 0.99 才算能用；0.9–0.99 只能粗略估计；&lt; 0.9 别用来报浓度。</>,
          <>LOD 是空白信号 + 3σ 反算出来的浓度，低于它的样品只能报「未检出」，报数字没有意义。LOQ 是能给出可信数值的下限。</>,
          <>点集中在左边一小段、右边一大段空白 = 浓度梯度没铺开，log 拟合会被最高那个点主导。</>,
        ]} />
      </Panel>

      <Panel title="样品浓度" sub="浓度列留空的行被当作未知样品">
        {verdicts.length ? (
          <div className="overflow-hidden rounded-2xl bg-background/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>文件</TableHead>
                  <TableHead>分组</TableHead>
                  <TableHead>响应</TableHead>
                  <TableHead>判定</TableHead>
                  <TableHead>浓度</TableHead>
                  <TableHead>95% 区间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {verdicts.map((v) => (
                  <TableRow key={v.file}>
                    <TableCell className="max-w-[240px] truncate text-muted-foreground">{v.file}</TableCell>
                    <TableCell className="text-muted-foreground">{v.group}</TableCell>
                    <TableCell className="tabular-nums">{fmtNum(v.value, 3)}</TableCell>
                    <TableCell><VerdictBadge v={v.verdict} /></TableCell>
                    <TableCell className="font-medium tabular-nums">{v.verdict === 'positive' ? fmtConc(v.C) : '—'}</TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">{v.C_lo != null ? fmtConc(v.C_lo) + ' ~ ' + fmtConc(v.C_hi) : '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <p className="text-xs text-muted-foreground">没有未知样品（浓度列全部填了值）。</p>}
      </Panel>
    </div>
  )
}

function MiniKV({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-background/60 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-lg font-semibold leading-none tabular-nums">{value}</div>
    </div>
  )
}
