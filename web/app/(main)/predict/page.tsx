'use client'

import { useEffect, useState } from 'react'
import { useFolder } from '@/lib/folder-context'
import { getRegression } from '@/lib/api'
import type { Regression } from '@/lib/types'
import { Badge, Card, CardBody, HowTo, Note, SectionTitle, StatCard, Table, Td } from '@/components/ui'
import { ImportanceBars, LearnCurve, ParityChart } from '@/components/charts'

function rpdTone(rpd: number): 'ok' | 'info' | 'warn' | 'bad' {
  if (rpd >= 3) return 'ok'
  if (rpd >= 2.4) return 'info'
  if (rpd >= 1.5) return 'warn'
  return 'bad'
}

function rpdWord(rpd: number): string {
  if (rpd >= 3) return '可用于筛查'
  if (rpd >= 2.4) return '勉强可定量'
  if (rpd >= 1.5) return '只能粗估'
  return '不能用'
}

export default function PredictPage() {
  const { folder, order, refFrac, technique, loading: ctxLoading } = useFolder()
  const [reg, setReg] = useState<Regression | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!folder) return
    let alive = true
    setLoading(true)
    setError(null)
    // drop the previous folder's result, otherwise the page keeps showing it
    // while the new (slow) regression request is still running
    setReg(null)
    getRegression(folder, order, refFrac, technique)
      .then((r) => { if (alive) { setReg(r); setLoading(false) } })
      .catch((e) => { if (alive) { setError(String(e)); setLoading(false) } })
    return () => { alive = false }
  }, [folder, order, refFrac, technique])

  // the zoo is not fixed: XGBoost only shows up when its wheel is installed
  const nModels = reg?.models?.length
    ? new Set(reg.models.map((r) => r.name)).size
    : 10

  const head = (
    <div>
      <h1 className="text-[26px] font-semibold tracking-tight text-[#101828]">预测模型</h1>
      <p className="mt-1 text-[12.5px] text-[#667085]">
        {nModels} 个模型 · 整条曲线与手工特征两套输入 · 留一独立单元交叉验证 · 超参数只在训练折里搜
      </p>
    </div>
  )

  if (ctxLoading || (loading && !reg)) {
    return (
      <div className="space-y-4">
        {head}
        <Note tone="info" title="正在训练模型">
          逐个拟合全部候选模型并做嵌套交叉验证（线性回归 / 岭回归 / PLS / SVR-RBF / SVR-线性核 /
          随机森林 / 梯度提升 / XGBoost / BP-ANN / 高斯过程），首次约 20 秒，之后走缓存。
        </Note>
      </div>
    )
  }
  if (error) return <div className="space-y-4">{head}<Note tone="bad" title="后端没有响应">{error}</Note></div>
  if (!reg) return null

  if (reg.error) {
    return (
      <div className="space-y-4">
        {head}
        <Note tone="warn" title="这个文件夹还训练不出预测模型">{reg.error}</Note>
        <Card>
          <CardBody className="space-y-2 text-[12.5px] leading-relaxed text-[#475467]">
            <div className="font-semibold text-[#101828]">预测模型要的是「同一个条件、不同浓度」，现在缺的是这一列</div>
            <div>标准点 <span className="font-medium text-[#101828] tnum">{reg.n_standards ?? 0}</span> 条 ·
              不同浓度 <span className="font-medium text-[#101828] tnum">{reg.n_levels ?? 0}</span> 个 ·
              独立电极 <span className="font-medium text-[#101828] tnum">{reg.n_electrodes ?? 0}</span> 支 ·
              批次 <span className="font-medium text-[#101828] tnum">{reg.n_batches ?? 0}</span> 个</div>
            <div>最低门槛：<b>6 条标准点、3 个不同浓度、3 支独立电极</b>（或 2 个批次）。</div>
            <div className="text-[#98a2b3]">
              一天能做完的最小方案：空白 3 支 + 10 nM 3 支 + 1 µM 3 支 = 9 支电极。
              做完回到「数据」页把浓度填进去，这一页立刻就有东西。
            </div>
          </CardBody>
        </Card>
      </div>
    )
  }

  const rows = reg.models || []
  const best = reg.best_row
  const pred = reg.best_pred
  const learn = reg.learning?.points || []
  const imp = (reg.importance?.rows || []).map((r) => ({
    feature: r.feature, label: r.feature, v: r.v,
  }))
  const last = learn.length ? learn[learn.length - 1] : null

  return (
    <div className="space-y-4">
      {head}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="最佳模型"
          value={reg.best || '—'}
          sub={'输入：' + (reg.best_set || '') + ' · ' + (reg.mode === 'electrode' ? '留一电极' : '留一批次')}
        />
        <StatCard
          label="R²"
          value={best ? best.r2.toFixed(3) : '—'}
          sub={reg.n_standards + ' 条标准点 · ' + (reg.n_levels || 0) + ' 个浓度 · ' + (reg.decades ?? 0).toFixed(1) + ' 个数量级'}
        />
        <StatCard
          label="误差倍数"
          value={best?.factor ? best.factor.toFixed(2) + '×' : '—'}
          sub={best?.rmse_dex != null ? best.rmse_dex.toFixed(2) + ' dex（预测偏离真值的典型倍数）' : ''}
        />
        <StatCard
          label="RPD"
          value={best ? best.rpd.toFixed(2) : '—'}
          sub={best ? rpdWord(best.rpd) + ' · >3 才算能筛查' : ''}
        />
      </div>

      <Note tone="mute" title="这几个数字怎么读">
        <b>R²</b> 越接近 1 越好，但它会被浓度范围放大 —— 跨 5 个数量级的 0.94 比跨 1 个数量级的 0.99 更难。
        <b className="ml-1">RPD</b> = 浓度本身的离散度 ÷ 预测误差，&gt;3 才算能用于筛查，&lt;1.5 基本不能用。
        <b className="ml-1">误差倍数</b> 是 10 的对数误差次方：2.7× 意思是「报 100 nM 时真值大概在 37–270 nM 之间」。
        <div className="mt-1 text-[12px] text-[#98a2b3]">
          对照 Food Chem 2025 的镉传感器：R² 0.9904–0.9948、RPD 3.37 —— 人家的标准点是 0.1–200 µM 逐点实测、多支电极重复。
        </div>
      </Note>

      <Card>
        <CardBody>
          <SectionTitle sub="按 R² 排序 · 同一批标准点、同一套留出规则，只换模型">
            模型对比
          </SectionTitle>
          <Table head={['模型', '输入', 'R²', 'RMSE (dex)', '误差倍数', 'RPD', '结论']}>
            {rows.map((m, i) => (
              <tr key={m.set + m.name} className={i === 0 ? 'bg-[#f9fafb]' : undefined}>
                <Td className="font-medium">
                  {m.name}
                  {i === 0 ? <span className="ml-2"><Badge tone="ok">最佳</Badge></span> : null}
                </Td>
                <Td className="text-[#667085]">{m.set}</Td>
                <Td>{m.r2.toFixed(3)}</Td>
                <Td>{m.rmse_dex != null ? m.rmse_dex.toFixed(2) : m.rmse.toFixed(2)}</Td>
                <Td>{m.factor ? m.factor.toFixed(2) + '×' : '—'}</Td>
                <Td>{m.rpd.toFixed(2)}</Td>
                <Td><Badge tone={rpdTone(m.rpd)}>{rpdWord(m.rpd)}</Badge></Td>
              </tr>
            ))}
          </Table>
          <div className="mt-3 space-y-1 text-[12px] leading-relaxed text-[#98a2b3]">
            <div>
              非线性模型（SVR-RBF / 高斯过程）赢在线性校准开始弯曲的两端；如果线性回归就是最好的，
              说明这批数据还在线性区里 —— 这本身也是一个结论，不必硬上神经网络。
            </div>
            <div>
              BP-ANN 垫底是正常的：{reg.n_standards} 条标准点喂不饱一个神经网络（Food Chem 那篇是几百条曲线）。
              样本少于 100 条时，SVR-RBF / 高斯过程才是合适的选择 —— 它们的参数量由数据自己定。
            </div>
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardBody>
            <SectionTitle sub={'虚线是理想线 · ' + (reg.best || '') + ' 留出预测'}>真值 vs 预测</SectionTitle>
            {pred && pred.true.length ? <ParityChart truth={pred.true} pred={pred.pred} /> : <div className="py-10 text-center text-[12.5px] text-[#98a2b3]">没有预测点</div>}
            <HowTo title="怎么读这张真值-预测散点图" items={[
              <><b>每个点 = 一个标准点曲线</b>。横轴是这个样品<b>已知</b>的浓度（你填进数据表的真值），纵轴是模型<b>只看曲线</b>猜出来的浓度。双对数坐标。</>,
              <>灰色虚线是理想线（猜得完全准）。点越贴近虚线越好；点整体在虚线上方 = 模型系统性高估，在下方 = 系统性低估。</>,
              <>点<b>沿着虚线散开</b>是随机误差（正常，可以靠多测取平均压下去）；点<b>偏离虚线形成一条斜带或弧形</b>说明模型有系统偏差（校准线没选对，或超出线性范围）。</>,
              <>这张图上的点全部来自"留一电极"的预测 —— 也就是模型<b>没见过</b>这支电极。所以它代表的是"换一支新电极还能猜多准"，不是"拟合得多好"。</>,
              <>点很少（十几二十个）时这张图会很"好看"或很"难看"，都是偶然。要看旁边的误差倍数和 RPD，别只看图。</>,
            ]} />
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <SectionTitle sub="再多做几支电极，误差会掉到多少">学习曲线</SectionTitle>
            {learn.length ? (
              <>
                <LearnCurve points={learn} />
                <div className="mt-2 text-[12px] leading-relaxed text-[#98a2b3]">
                  {last
                    ? '训练到 ' + last.n_train + ' 支电极时，留出误差约 ' + last.rmse.toFixed(2) + ' dex（' +
                      Math.pow(10, last.rmse).toFixed(1) + '×）。曲线还在往下走就说明数据不够，走平了就是这批数据的极限。'
                    : ''}
                </div>
              </>
            ) : (
              <div className="py-10 text-center text-[12.5px] text-[#98a2b3]">{reg.learning?.error || '独立单元太少，画不出学习曲线'}</div>
            )}
          </CardBody>
        </Card>
      </div>

      {imp.length ? (
        <Card>
          <CardBody>
            <SectionTitle sub="打乱这个特征后误差涨多少 · 在留出的电极上算">哪些特征真正在起作用</SectionTitle>
            <ImportanceBars rows={imp} />
            <div className="mt-2 text-[12px] leading-relaxed text-[#98a2b3]">
              峰电流和比值排在前面是应该的 —— 它们是 MB 的响应本身。如果开路电位、末端电流这类
              「跟浓度无关」的量排得很高，说明模型在吃电极的整体状态，而不是在测链霉素。
            </div>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardBody className="space-y-1.5 text-[12px] leading-relaxed text-[#667085]">
          <div className="text-[13px] font-semibold text-[#101828]">方法（这一段决定了上面那些数字能不能信）</div>
          <div>· 验证单位是<b>整支电极</b>（或<b>整个批次</b>），不是单条曲线 —— 同一支电极扫 3 次不算 3 个独立样本。</div>
          <div>· 超参数搜索在<b>训练折内部</b>完成（嵌套交叉验证），被留出的电极从不参与调参。</div>
          <div>· 标准点跨 {(reg.decades ?? 0).toFixed(1)} 个数量级，模型拟合 log10(C)，所以误差用 dex 表示；跨不到一个数量级时自动改用 C 本身。</div>
          <div>· 两套输入都试：整条基线校正曲线（{reg.meta?.n_points ?? 80} 点，不丢形状信息）与 12 个手工特征（峰高、峰位、电荷、比值）。</div>
          <div>· 高斯过程还会给出每个预测的不确定度，BP-ANN 对应 Food Chem 那篇三种抗生素同时检测的做法。</div>
        </CardBody>
      </Card>
    </div>
  )
}
