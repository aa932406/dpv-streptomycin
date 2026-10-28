'use client'

import Link from 'next/link'
import {
  AlertTriangle, ArrowRight, CheckCircle2, Gauge, Layers, ScanLine, Users, XCircle,
} from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/common/layout/PageHeader'
import { StatCard } from '@/components/common/layout/StatCard'
import { CurvesChart, Legend } from '@/components/charts'
import { NoCurves, PageError, PageLoading } from '@/components/PageState'
import { fmtConc, fmtNum, fmtP } from '@/lib/utils'

function explainFitError(e: string): { title: string; detail: string } {
  if (!e) return { title: '校准不可用', detail: '' }
  if (e.includes('no row has a concentration')) {
    return { title: '没有填任何浓度', detail: '在数据表的「浓度」列填上标准品的真实浓度（M），空白填 0，未知样品留空。' }
  }
  if (e.includes('at least 3 different concentrations')) {
    return { title: '这批数据给不出浓度', detail: '这批数据只有一个浓度水平，画不出校准曲线。定量至少需要 3 个浓度梯度（例如 0 / 10 nM / 1 µM），每个浓度 3 支独立电极。' }
  }
  if (e.includes('at least 4 standards')) {
    return { title: '标准点太少', detail: '有浓度的标准点不足 4 条。至少 3 个浓度 × 每浓度 1 支以上，最好每浓度 3 支。' }
  }
  if (e.includes('not usable')) {
    return { title: '峰电流不随浓度变化', detail: '校准拟合的 R² 太低或斜率接近 0，说明响应和浓度没有线性关系，不能拿来算浓度。' }
  }
  return { title: '校准不可用', detail: e }
}

function Panel({ title, sub, children, className }: {
  title: string
  sub?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={'rounded-[20px] bg-muted p-4 ' + (className || '')}>
      <div className="mb-3 flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-medium">{title}</h2>
        {sub ? <span className="text-[11px] text-muted-foreground">{sub}</span> : null}
      </div>
      {children}
    </section>
  )
}

function VerdictRow({ v }: { v: any }) {
  const positive = v.verdict === 'positive'
  const negative = v.verdict === 'negative'
  const Icon = positive ? CheckCircle2 : negative ? XCircle : AlertTriangle
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-background/60 px-3.5 py-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className={'grid size-7 shrink-0 place-items-center rounded-full bg-white/70 dark:bg-white/[0.05] ' +
          (positive ? 'text-emerald-600' : negative ? 'text-muted-foreground' : 'text-amber-600')}>
          <Icon className="size-4" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-xs font-medium">{v.file}</div>
          <div className="truncate text-[11px] text-muted-foreground">
            {v.group} · {v.electrode}{v.batch ? ' · 批次 ' + v.batch : ''}
          </div>
        </div>
      </div>
      <div className="text-right">
        <div className={'text-sm font-semibold tabular-nums ' +
          (positive ? 'text-emerald-600' : negative ? 'text-muted-foreground' : 'text-amber-600')}>
          {positive ? (v.C_text || fmtConc(v.C)) : negative ? '未检出' : '无法判定'}
        </div>
        {positive && v.C_lo != null ? (
          <div className="text-[11px] tabular-nums text-muted-foreground">
            95% CI {fmtConc(v.C_lo)} – {fmtConc(v.C_hi)}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default function VerdictPage() {
  const { data, loading, error } = useFolder()

  if (loading) return <PageLoading />
  if (error) return <PageError title="后端没有响应" detail={error} />
  if (!data || !data.meta || !data.meta.n_curves) return <NoCurves />

  const m = data.meta
  const fitErr = data.fit?.error
  const sc = data.screening
  const verdicts = data.verdicts || []
  const fb = data.fit_batch
  const useBatch = !!fb && !fb.error && (fb.batches?.length || 0) > 1 && verdicts.length > 0
  const posCount = verdicts.filter((v) => v.verdict === 'positive').length
  const negCount = verdicts.filter((v) => v.verdict === 'negative').length
  const unkCount = verdicts.length - posCount - negCount

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <PageHeader
        title="结论"
        description={`文件夹 ${m.folder} · ${m.n_curves} 条曲线 · ${m.n_electrodes} 支独立电极`}
        actions={
          <>
            <Button variant="outline" size="sm" className="rounded-full" asChild>
              <Link href="/data">
                核对数据
                <ArrowRight />
              </Link>
            </Button>
            <Button variant="outline" size="sm" className="rounded-full" asChild>
              <Link href="/calib">校准与定量</Link>
            </Button>
          </>
        }
      />

      <section className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-5">
        <StatCard label="曲线" value={m.n_curves} hint="参与分析的扫描" icon={ScanLine} delay={0} />
        <StatCard label="独立电极" value={m.n_electrodes} hint="统计上的真实重复数" icon={Users} delay={0.04} />
        <StatCard label="分组" value={m.n_groups} hint="实验条件" icon={Layers} delay={0.08} />
        <StatCard
          label="QC 合格"
          value={m.n_qc + ' / ' + m.n_curves}
          hint={'内参门槛 ' + fmtNum(m.qc_threshold, 2) + ' µA'}
          icon={Gauge}
          tone={m.n_qc === 0 ? 'danger' : m.n_qc < m.n_curves * 0.6 ? 'warning' : 'neutral'}
          delay={0.12}
        />
        <StatCard
          label="检出样品"
          value={verdicts.length ? `${posCount} / ${verdicts.length}` : '—'}
          hint={verdicts.length ? `未检出 ${negCount} · 无法判定 ${unkCount}` : '浓度列留空的行算未知样品'}
          icon={CheckCircle2}
          tone={posCount ? 'success' : verdicts.length ? 'neutral' : 'neutral'}
          delay={0.16}
        />
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel
          className="lg:col-span-2"
          title="样品判定"
          sub={fitErr && !useBatch ? '这批数据没有浓度梯度，只能做定性筛查' : useBatch ? '每个样品用自己那一批的截距定量' : ''}
        >
          {useBatch ? (
            <div className="space-y-2">
              <div className="rounded-2xl bg-blue-500/10 px-3.5 py-3 text-[11.5px] leading-5 text-blue-700 ring-1 ring-blue-500/20 dark:text-blue-300">
                这批数据跨 {fb.batches?.length || 0} 个批次，单条全局校准线用不了，已改为按批标定：
                每批用自己那天的标准点定截距。合并 R² {fmtNum(fb.r2, 3)}，
                全局单线 R² {fmtNum(fb.pooled_r2, 3)}，留一批次误差 {fmtNum(fb.rmse_log_lobo, 2)} dex。
              </div>
              {verdicts.map((v) => <VerdictRow key={v.file} v={v} />)}
            </div>
          ) : fitErr ? (
            <>
              <div className="flex items-start gap-2.5 rounded-2xl bg-amber-500/10 px-3.5 py-3 ring-1 ring-amber-500/20">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
                <div className="min-w-0 space-y-1">
                  <div className="text-xs font-medium">{explainFitError(fitErr).title}</div>
                  <p className="text-[11px] leading-4 text-muted-foreground">{explainFitError(fitErr).detail}</p>
                </div>
              </div>

              {sc && !sc.error ? (
                <div className="mt-4">
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    定性筛查
                    <Badge variant="secondary">{sc.neg_group}</Badge>
                    对比
                    <Badge variant="outline">{sc.pos_group}</Badge>
                    <span>{sc.n_neg_elec} 支 / {sc.n_pos_elec} 支独立电极</span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <MiniStat label="信号比" value={sc.ratio.toFixed(2) + '×'} />
                    <MiniStat label="电极级 p 值" value={fmtP(sc.p)} />
                    <MiniStat label="效应量 d" value={fmtNum(sc.effect_d, 2)} />
                    <MiniStat label="判别准确率" value={(sc.accuracy * 100).toFixed(0) + '%'} />
                  </div>
                  <div className="mt-3">
                    {!sc.separates ? (
                      <div className="rounded-2xl bg-red-500/10 px-3.5 py-3 text-[11.5px] leading-5 text-red-700 ring-1 ring-red-500/20 dark:text-red-300">
                        这条截断值切不开两组：阴性对照 {sc.false_pos}/{sc.n_neg_elec} 支被判成阳性，
                        阳性样品 {sc.missed}/{sc.n_pos_elec} 支漏检。先把空白 CV 从
                        {' '}{Math.abs((sc.neg_sd / sc.neg_mean) * 100).toFixed(0)}% 压到 15–25% 再谈阈值。
                      </div>
                    ) : (
                      <div className="rounded-2xl bg-emerald-500/10 px-3.5 py-3 text-[11.5px] leading-5 text-emerald-700 ring-1 ring-emerald-500/20 dark:text-emerald-300">
                        两组完全分开（{sc.n_neg_elec} vs {sc.n_pos_elec} 支电极），截断值
                        {' '}{fmtNum(sc.cutoff, 2)}，可用于定性判断。注意：只能给「检出 / 未检出」，给不出浓度。
                      </div>
                    )}
                  </div>
                  {sc.p_floor > 0.05 ? (
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      每组电极数太少，Mann-Whitney 的 p 值最小只能到 {sc.p_floor.toFixed(2)}。
                      每组至少 4 支电极才可能得到 p &lt; 0.05。
                    </p>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : verdicts.length ? (
            <div className="space-y-2">
              {verdicts.map((v) => <VerdictRow key={v.file} v={v} />)}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">没有待测样品。把浓度列留空的行当作未知样品。</p>
          )}
        </Panel>

        <Panel title="体系状态" sub="这次分析的可信度取决于这几项">
          <div className="divide-y divide-border/60">
            <KeyVal k="扫描类型" v={m.technique_cn || '—'} />
            <KeyVal k="扫描窗口" v={m.window[1].toFixed(2) + ' → ' + m.window[0].toFixed(2) + ' V'} />
            <KeyVal k="响应指标" v={m.metric_cn} />
            <KeyVal k="响应方向" v={data.fit?.direction === 'signal-off' ? '信号关闭' : data.fit?.direction === 'signal-on' ? '信号开启' : '—'} />
            <KeyVal k="内参中位数" v={fmtNum(m.qc_median, 2) + ' µA'} />
            <KeyVal k="校准 R²" v={(useBatch ? fb?.r2 : data.fit?.r2) != null ? fmtNum(useBatch ? fb!.r2! : data.fit!.r2!, 3) : '—'} />
            <KeyVal
              k="LOD"
              v={useBatch
                ? (fb?.batches?.length ? '各批 ' + fmtConc(Math.min(...fb.batches.map((b) => b.LOD_M ?? Infinity))) + ' 起' : '—')
                : data.fit?.LOD_M != null ? fmtConc(data.fit.LOD_M) : '—'}
            />
          </div>
        </Panel>
      </div>

      <Panel title="曲线" sub={'各条件平均曲线（基线校正，' + m.n_points + ' 点）'}>
        <div className="mb-2">
          <Legend series={data.curves.series} />
        </div>
        <CurvesChart grid={data.curves.grid} series={data.curves.series} height={300} />
      </Panel>

      {data.errors?.length ? (
        <Panel title="跳过的文件" sub={data.errors.length + ' 个文件没参与分析'}>
          <div className="max-h-52 space-y-1 overflow-auto scroll-slim">
            {data.errors.map((e) => (
              <div key={e.file} className="flex gap-2 text-[11px]">
                <span className="shrink-0 text-foreground">{e.file}</span>
                <span className="text-muted-foreground">{e.error}</span>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-background/60 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-lg font-semibold leading-none tabular-nums">{value}</div>
    </div>
  )
}

function KeyVal({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <span className="text-[11px] text-muted-foreground">{k}</span>
      <span className="text-[11px] font-medium tabular-nums">{v}</span>
    </div>
  )
}
