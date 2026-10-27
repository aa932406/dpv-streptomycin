'use client'

import { useFolder } from '@/lib/folder-context'
import { Badge, Card, Loading, Note, SectionTitle, StatCard, Table, Td } from '@/components/ui'
import { ImportanceBars, PermHist } from '@/components/charts'
import { fmtNum, fmtP } from '@/lib/utils'

export default function ModelsPage() {
  const { data, loading, error } = useFolder()
  if (loading) return <Loading />
  if (error) return <Note tone="bad" title="后端没有响应">{error}</Note>
  if (!data) return null

  const m = data.model
  const imp = data.importance || []
  const bal = m?.balanced_accuracy ?? null
  const minElec = m?.min_elec_per_class ?? null
  const nulls = m?.perm?.null ?? []
  const flatNull = nulls.length > 0 && Math.max(...nulls) - Math.min(...nulls) < 1e-9

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight text-[#101828]">建模</h1>
        <p className="mt-1 text-[12.5px] text-[#667085]">
          用整条曲线（{data.meta.n_points} 点）训练 LDA · 留一电极交叉验证 · 电极级置换检验
        </p>
      </div>

      {!m || m.error ? (
        <Note tone="warn" title="这个文件夹还训练不出分类器">{m?.error || '没有可用的分组标签。'}</Note>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard
              label="平衡准确率"
              value={bal != null ? (bal * 100).toFixed(1) + '%' : '—'}
              sub={m.n_folds + ' 折 · ' + m.n_scans + ' 条曲线 · 各类召回平均'}
            />
            <StatCard
              label="原始准确率"
              value={(m.accuracy! * 100).toFixed(1) + '%'}
              sub="会被样本最多的那一类主导"
            />
            <StatCard label="瞎猜水平" value={(m.chance! * 100).toFixed(1) + '%'} sub={(m.labels?.length || 0) + ' 类'} />
            <StatCard
              label="置换检验 p"
              value={m.perm ? fmtP(m.perm.p_value) : '—'}
              sub={m.perm ? '零分布均值 ' + (m.perm.null_mean * 100).toFixed(0) + '%（同样按平衡准确率）' : ''}
            />
          </div>

          {minElec != null && minElec <= 1 ? (
            <Note tone="warn" title="这个文件夹做不了留一电极分类 —— 每个条件只有 1 支电极">
              留一电极时，被留出的那一支电极所代表的类别从训练集里整个消失，模型没有任何机会答对，
              准确率在数学上必然是 0%。这不是模型差，是这批数据没有独立重复：
              {(m.elec_per_class ? Object.entries(m.elec_per_class) : []).map(([g, n]) => g + ' ' + n + ' 支').join(' · ')}。
              想让它有意义，每个条件至少做 2 支电极（3 支更稳）。
            </Note>
          ) : bal != null && bal <= m.chance! + 0.05 ? (
            <Note tone="warn" title="这个准确率与瞎猜没有区别">
              分组太多、每支电极的曲线太少时，分类器学不到东西。这个数字不能拿来下结论。
            </Note>
          ) : null}

          {m.perm && m.perm.p_value != null && m.perm.p_value >= 0.05 && !(minElec != null && minElec <= 1) ? (
            <Note tone="mute" title="置换检验不显著">
              打乱电极标签后，零分布里也能出现同样好的成绩（均值 {(m.perm.null_mean * 100).toFixed(0)}%，
              95 分位 {(m.perm.null_p95 * 100).toFixed(0)}%）。说明这几类的曲线差异还不足以支撑判别。
            </Note>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="px-5 py-4">
              <SectionTitle sub="行 = 真实，列 = 预测">混淆矩阵</SectionTitle>
              <Table head={['真实 \\ 预测', ...(m.labels || [])]}>
                {(m.confusion || []).map((row, i) => (
                  <tr key={i} className="border-b border-[#f2f4f7] last:border-0">
                    <Td className="text-[#475467]">{m.labels?.[i]}</Td>
                    {row.map((v, j) => (
                      <Td key={j}>
                        {v > 0 ? <Badge tone={i === j ? 'ok' : 'bad'}>{v}</Badge> : <span className="text-[#d0d5dd]">0</span>}
                      </Td>
                    ))}
                  </tr>
                ))}
              </Table>
            </Card>

            <Card className="px-5 py-4">
              <SectionTitle sub={m.perm ? '打乱电极标签 ' + m.perm.null.length + ' 次' : ''}>置换检验</SectionTitle>
              {m.perm && !flatNull ? <PermHist nulls={m.perm.null} observed={m.perm.observed} p95={m.perm.null_p95} /> : null}
              {m.perm && !flatNull ? (
                <p className="mt-2 text-[11.5px] leading-relaxed text-[#98a2b3]">
                  红线是实测平衡准确率，灰虚线是零分布的 95 分位。实测线要明显落在分布右侧才算真学到东西。
                </p>
              ) : null}
              {flatNull ? (
                <Note tone="mute" title="置换检验画不出分布">
                  打乱电极标签后，100 次全部得到同一个分数（{(m.perm.null[0] * 100).toFixed(0)}%），
                  零分布退化成一个点。这通常意味着每个条件只有 1 支电极 —— 打乱后训练集里
                  根本没有可学的类别。先补重复，再看这张图。
                </Note>
              ) : null}
            </Card>
          </div>

          <Card className="px-5 py-4">
            <SectionTitle sub="随机森林，手工特征">特征重要性</SectionTitle>
            {imp.length ? <ImportanceBars rows={imp} /> : <Note tone="mute">特征不够，算不出重要性。</Note>}
          </Card>
        </>
      )}
    </div>
  )
}
