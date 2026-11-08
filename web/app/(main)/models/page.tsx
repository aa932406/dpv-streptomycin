'use client'

import { Activity, Brain, Grid2x2, TrendingUp } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader } from '@/components/common/layout/PageHeader'
import { StatCard } from '@/components/common/layout/StatCard'
import { ImportanceBars, PermHist } from '@/components/charts'
import { Panel } from '@/components/Panel'
import { NoCurves, PageError, PageLoading } from '@/components/PageState'
import { fmtP } from '@/lib/utils'

function Notice({ title, children, tone = 'warning' }: {
  title: string
  children: React.ReactNode
  tone?: 'warning' | 'muted'
}) {
  return (
    <div className={'rounded-xl px-4 py-3 text-[11px] leading-5 ' +
      (tone === 'warning' ? 'bg-amber-500/10 text-foreground ring-1 ring-amber-500/20' : 'bg-muted text-muted-foreground')}>
      <div className="mb-1 font-medium">{title}</div>
      {children}
    </div>
  )
}

export default function ModelsPage() {
  const { data, loading, error } = useFolder()
  if (loading) return <PageLoading />
  if (error) return <PageError title="后端没有响应" detail={error} />
  if (!data || !data.meta?.n_curves) return <NoCurves />

  const m = data.model
  const imp = data.importance || []
  const balanced = m?.balanced_accuracy
  const minElec = m?.min_elec_per_class
  const permutation = m?.perm
  const nulls = permutation?.null || []
  const flatNull = nulls.length > 0 && Math.max(...nulls) - Math.min(...nulls) < 1e-9

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <PageHeader
        title="分类建模"
        description={`整条曲线 · 留一电极交叉验证 · 电极级置换检验 · ${data.meta.n_curves} 条曲线`}
      />

      {!m || m.error ? (
        <Notice title="这个文件夹还训练不出分类器">{m?.error || '没有可用的分组标签。'}</Notice>
      ) : (
        <>
          <section className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
            <StatCard label="平衡准确率" value={balanced != null ? (balanced * 100).toFixed(1) + '%' : '—'}
              hint={m.n_folds + ' 折 · ' + m.n_scans + ' 条曲线 · 各类召回平均'} icon={Brain} tone="accent" />
            <StatCard label="原始准确率" value={m.accuracy != null ? (m.accuracy * 100).toFixed(1) + '%' : '—'}
              hint="会被样本最多的那一类主导" icon={TrendingUp} />
            <StatCard label="瞎猜水平" value={m.chance != null ? (m.chance * 100).toFixed(1) + '%' : '—'}
              hint={(m.labels?.length || 0) + ' 类'} icon={Grid2x2} />
            <StatCard label="置换检验 p" value={permutation ? fmtP(permutation.p_value) : '—'}
              hint={permutation ? '零分布均值 ' + (permutation.null_mean * 100).toFixed(0) + '%' : ''}
              icon={Activity} />
          </section>

          {minElec != null && minElec <= 1 ? (
            <Notice title="无法进行有效的留一电极分类">
              每个条件只有 1 支独立电极，被留出的类别会从训练集中消失。请为每个条件增加独立电极重复；至少 2 支，建议 3 支以上。
            </Notice>
          ) : balanced != null && m.chance != null && balanced <= m.chance + 0.05 ? (
            <Notice title="当前结果接近随机猜测">这个分类器尚未显示出可靠的区分能力，不应据此下结论。</Notice>
          ) : null}

          {permutation && permutation.p_value >= 0.05 && !(minElec != null && minElec <= 1) ? (
            <Notice title="置换检验未达到显著性" tone="muted">
              打乱电极标签后，零分布也能出现相近的成绩。当前数据不足以支持模型具有可重复的判别能力。
            </Notice>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="混淆矩阵" sub="行 = 真实类别，列 = 预测类别">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>真实 \ 预测</TableHead>
                      {(m.labels || []).map((label) => <TableHead key={label}>{label}</TableHead>)}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(m.confusion || []).map((row, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-muted-foreground">{m.labels?.[i]}</TableCell>
                        {row.map((value, j) => (
                          <TableCell key={j}>
                            {value > 0 ? <Badge variant={i === j ? 'default' : 'outline'}>{value}</Badge> : '0'}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Panel>

            <Panel title="电极级置换检验" sub={permutation ? '打乱标签 ' + nulls.length + ' 次' : undefined}>
              {permutation && !flatNull ? <PermHist nulls={nulls} observed={permutation.observed} p95={permutation.null_p95} /> : null}
              {flatNull ? (
                <Notice title="置换零分布退化为单个分数" tone="muted">
                  {nulls.length} 次置换得到同一个结果（{(nulls[0] * 100).toFixed(0)}%）。这通常表示独立电极数不足，无法估计稳定的零分布。
                </Notice>
              ) : null}
              {!permutation ? <p className="text-xs text-muted-foreground">当前数据无法计算置换检验。</p> : null}
            </Panel>
          </div>

          <Panel title="特征重要性" sub="随机森林 · 手工提取的曲线特征">
            {imp.length ? <ImportanceBars rows={imp} /> : <p className="text-xs text-muted-foreground">特征不够，算不出重要性。</p>}
          </Panel>

          <p className="text-[11px] leading-5 text-muted-foreground">
            分类结果只描述当前数据集中的组间区分情况，不是通用目标物识别器。独立重复单位是电极，不是同一电极的重复扫描。
          </p>
        </>
      )}
    </div>
  )
}
