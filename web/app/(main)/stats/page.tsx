'use client'

import { Activity, FlaskConical, Grid2x2, TrendingUp } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader } from '@/components/common/layout/PageHeader'
import { StatCard } from '@/components/common/layout/StatCard'
import { GroupBars, PcaScatter } from '@/components/charts'
import { HowTo } from '@/components/HowTo'
import { Panel } from '@/components/Panel'
import { NoCurves, PageError, PageLoading } from '@/components/PageState'
import { featureCN, fmtNum, fmtP } from '@/lib/utils'

export default function StatsPage() {
  const { data, loading, error } = useFolder()
  if (loading) return <PageLoading />
  if (error) return <PageError title="后端没有响应" detail={error} />
  if (!data || !data.meta?.n_curves) return <NoCurves />

  const st = data.stats
  const anova = st?.anova || []
  const tukey = st?.tukey || []
  const pca = data.pca
  const finite = anova.filter((r) => isFinite(r.F))
  const top = finite.length ? finite.reduce((a, b) => (b.eta2 > a.eta2 ? b : a)) : null
  const useQc = data.groups.some((g) => (g.n_qc ?? 0) > 0)
  const groupColors = Object.fromEntries(
    data.groups.filter((g) => g.color).map((g) => [g.name, g.color as string]),
  )
  const bars = data.groups
    .filter((g) => (useQc ? g.mean_qc != null : g.mean != null))
    .map((g) => ({
      name: g.name,
      mean: (useQc ? g.mean_qc! : g.mean!),
      sd: (useQc ? g.sd_qc || 0 : g.sd || 0),
      color: g.color,
    }))
  const sig = anova.filter((r) => r.p < 0.05).length

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <PageHeader
        title="统计"
        description="组间差异检验 · 主成分分析 · 以曲线为 n 的单因素检验（真正的独立重复是电极）"
      />

      <section className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
        <StatCard label="分组数" value={data.meta.n_groups} hint="参与检验的条件" icon={Grid2x2} />
        <StatCard
          label="最强差异指标"
          value={top ? featureCN(top.feature, top.label) : '—'}
          hint={top ? 'η² = ' + fmtNum(top.eta2, 3) : ''}
          icon={TrendingUp}
          tone={top ? 'accent' : 'neutral'}
          delay={0.04}
        />
        <StatCard
          label="PC1 解释率"
          value={pca?.var?.length ? (pca.var[0] * 100).toFixed(1) + '%' : '—'}
          hint={pca?.var?.length > 1 ? 'PC2 ' + (pca.var[1] * 100).toFixed(1) + '%' : ''}
          icon={FlaskConical}
          delay={0.08}
        />
        <StatCard
          label="显著指标数"
          value={sig + ' / ' + anova.length}
          hint="p < 0.05"
          icon={Activity}
          tone={sig ? 'success' : 'neutral'}
          delay={0.12}
        />
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="各条件响应均值" sub={data.meta.metric_cn + (useQc ? ' · 仅 QC 合格曲线' : ' · 全部曲线')}>
          <GroupBars rows={bars} />
        </Panel>
        <Panel title="PCA 得分" sub="整条曲线降到前三个主成分">
          {pca?.points?.length
            ? <PcaScatter points={pca.points} varPct={pca.var || []} groupColors={groupColors} />
            : <p className="text-xs text-muted-foreground">曲线太少，算不了 PCA。</p>}
          <HowTo title="怎么读这张 PCA 散点图" items={[
            <><b>每个点 = 一条曲线</b>（80–220 个电位点压缩成的两个坐标），不是一次测量里的多点。同组曲线应该挤在一起。</>,
            <>横轴 PC1、纵轴 PC2 是「最能解释数据差异的两个方向」，括号里的百分比是它们各自解释了多少总差异。PC1 占 50% 以上说明<b>一个因素</b>主导了全部差异。</>,
            <>两组<b>分开</b> = 曲线形状确实不同，条件有区分度；两组<b>叠在一起</b> = 曲线几乎一样，任何分类器都分不开（20261010 的 material 与 material+MB 就是叠在一起的）。</>,
            <>PC1 不是浓度、也不是信号强度，它只是「差异最大的那个方向」。想解释 PC1 到底代表什么，看它和哪个峰相关 —— 这需要载荷图，本页没画。</>,
            <>点少（每组 2–3 个）时，PCA 很容易画出「看起来分开了」的假象：换一条曲线位置就变。所以这里的图只能当参考，结论要看「结论」页的电极级检验。</>,
          ]} />
        </Panel>
      </div>

      <Panel title="单因素 ANOVA" sub="以曲线为观测单位，未按电极聚合">
        {anova.length ? (
          <div className="overflow-hidden rounded-2xl bg-background/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>指标</TableHead>
                  <TableHead>F</TableHead>
                  <TableHead>p</TableHead>
                  <TableHead>η²</TableHead>
                  <TableHead>n</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {anova.map((r) => (
                  <TableRow key={r.feature}>
                    <TableCell className="text-muted-foreground">{featureCN(r.feature, r.label)}</TableCell>
                    <TableCell className="tabular-nums">{fmtNum(r.F, 2)}</TableCell>
                    <TableCell>
                      {r.p < 0.05
                        ? <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">{fmtP(r.p)}</Badge>
                        : <span className="tabular-nums text-muted-foreground">{fmtP(r.p)}</span>}
                    </TableCell>
                    <TableCell className="tabular-nums">{fmtNum(r.eta2, 3)}</TableCell>
                    <TableCell className="tabular-nums">{r.n}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <p className="text-xs text-muted-foreground">组内曲线太少，算不出 ANOVA。</p>}
        <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
          伪重复警告：同一支电极的多次扫描不是独立重复。若每组只有 1 支电极，这里的 p 值不能引用。
        </p>
      </Panel>

      <Panel title="Tukey HSD 两两比较" sub={'指标：' + data.meta.metric_cn}>
        {tukey.length ? (
          <div className="overflow-hidden rounded-2xl bg-background/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>A</TableHead>
                  <TableHead>B</TableHead>
                  <TableHead>差值</TableHead>
                  <TableHead>p</TableHead>
                  <TableHead>95% 区间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tukey.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-muted-foreground">{r.A}</TableCell>
                    <TableCell className="text-muted-foreground">{r.B}</TableCell>
                    <TableCell className="tabular-nums">{fmtNum(r.diff, 3)}</TableCell>
                    <TableCell>
                      {r.p < 0.05
                        ? <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">{fmtP(r.p)}</Badge>
                        : <span className="tabular-nums text-muted-foreground">{fmtP(r.p)}</span>}
                    </TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">{fmtNum(r.lo, 2)} ~ {fmtNum(r.hi, 2)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <p className="text-xs text-muted-foreground">至少两个条件各有 2 条以上曲线才能做两两比较。</p>}
      </Panel>
    </div>
  )
}
