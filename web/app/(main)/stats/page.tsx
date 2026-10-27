'use client'

import { useFolder } from '@/lib/folder-context'
import { Badge, Card, HowTo, Loading, Note, SectionTitle, StatCard, Table, Td } from '@/components/ui'
import { GroupBars, PcaScatter } from '@/components/charts'
import { featureCN, fmtNum, fmtP } from '@/lib/utils'

export default function StatsPage() {
  const { data, loading, error } = useFolder()
  if (loading) return <Loading />
  if (error) return <Note tone="bad" title="后端没有响应">{error}</Note>
  if (!data) return null

  const st = data.stats
  const anova = st?.anova || []
  const tukey = st?.tukey || []
  const summary = st?.summary || []
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
      n: useQc ? (g.n_qc ?? 0) : g.n,
    }))

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight text-[#101828]">统计</h1>
        <p className="mt-1 text-[12.5px] text-[#667085]">
          组间差异检验 · 主成分分析 · 以曲线为 n 的单因素检验（注意：真正的独立重复是电极）
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="分组数" value={data.meta.n_groups} sub="参与检验的条件" />
        <StatCard label="最强差异指标" value={top ? featureCN(top.feature, top.label) : '—'} sub={top ? 'η² = ' + fmtNum(top.eta2, 3) : ''} />
        <StatCard label="PC1 解释率" value={pca?.var?.length ? (pca.var[0] * 100).toFixed(1) + '%' : '—'} sub={pca?.var?.length > 1 ? 'PC2 ' + (pca.var[1] * 100).toFixed(1) + '%' : ''} />
        <StatCard label="显著指标数" value={anova.filter((r) => r.p < 0.05).length + ' / ' + anova.length} sub="p < 0.05" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="px-5 py-4">
          <SectionTitle sub={data.meta.metric_cn + (useQc ? ' · 仅 QC 合格曲线' : ' · 全部曲线')}>各条件响应均值</SectionTitle>
          <GroupBars rows={bars} />
        </Card>
        <Card className="px-5 py-4">
          <SectionTitle sub="整条曲线降到前三个主成分">PCA 得分</SectionTitle>
          {pca?.points?.length ? <PcaScatter points={pca.points} varPct={pca.var || []} groupColors={groupColors} /> : <Note tone="mute">曲线太少，算不了 PCA。</Note>}
          <HowTo title="怎么读这张 PCA 散点图" items={[
            <><b>每个点 = 一条曲线</b>（80–220 个电位点压缩成的两个坐标），不是一次测量里的多点。同组曲线应该挤在一起。</>,
            <>横轴 PC1、纵轴 PC2 是"最能解释数据差异的两个方向"，括号里的百分比是它们各自解释了多少总差异。PC1 占 50% 以上说明<b>一个因素</b>主导了全部差异。</>,
            <>两组<b>分开</b> = 曲线形状确实不同，条件有区分度；两组<b>叠在一起</b> = 曲线几乎一样，任何分类器都分不开（20261010 的 material 与 material+MB 就是叠在一起的）。</>,
            <>PC1 不是浓度、也不是信号强度，它只是"差异最大的那个方向"。想解释 PC1 到底代表什么，看它和哪个峰相关 —— 这需要载荷图，本页没画。</>,
            <>点少（每组 2–3 个）时，PCA 很容易画出"看起来分开了"的假象：换一条曲线位置就变。所以这里的图只能当参考，结论要看「结论」页的电极级检验。</>,
          ]} />
        </Card>
      </div>

      <Card className="px-5 py-4">
        <SectionTitle sub="以曲线为观测单位，未按电极聚合">单因素 ANOVA</SectionTitle>
        {anova.length ? (
          <Table head={['指标', 'F', 'p', 'η²', 'n']}>
            {anova.map((r) => (
              <tr key={r.feature} className="border-b border-[#f2f4f7] last:border-0">
                <Td className="text-[#475467]">{featureCN(r.feature, r.label)}</Td>
                <Td>{fmtNum(r.F, 2)}</Td>
                <Td>{r.p < 0.05 ? <Badge tone="ok">{fmtP(r.p)}</Badge> : <span className="text-[#98a2b3]">{fmtP(r.p)}</span>}</Td>
                <Td>{fmtNum(r.eta2, 3)}</Td>
                <Td>{r.n}</Td>
              </tr>
            ))}
          </Table>
        ) : <Note tone="mute">组内曲线太少，算不出 ANOVA。</Note>}
        <p className="mt-3 text-[11.5px] leading-relaxed text-[#98a2b3]">
          伪重复警告：同一支电极的多次扫描不是独立重复。若每组只有 1 支电极，这里的 p 值不能引用。
        </p>
      </Card>

      <Card className="px-5 py-4">
        <SectionTitle sub={'指标：' + data.meta.metric_cn}>Tukey HSD 两两比较</SectionTitle>
        {tukey.length ? (
          <Table head={['A', 'B', '差值', 'p', '95% 区间']}>
            {tukey.map((r, i) => (
              <tr key={i} className="border-b border-[#f2f4f7] last:border-0">
                <Td className="text-[#475467]">{r.A}</Td>
                <Td className="text-[#475467]">{r.B}</Td>
                <Td>{fmtNum(r.diff, 3)}</Td>
                <Td>{r.p < 0.05 ? <Badge tone="ok">{fmtP(r.p)}</Badge> : <span className="text-[#98a2b3]">{fmtP(r.p)}</span>}</Td>
                <Td className="text-[#98a2b3]">{fmtNum(r.lo, 2)} ~ {fmtNum(r.hi, 2)}</Td>
              </tr>
            ))}
          </Table>
        ) : <Note tone="mute">至少两个条件各有 2 条以上曲线才能做两两比较。</Note>}
      </Card>
    </div>
  )
}
