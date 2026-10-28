'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Activity, AlertTriangle, Gauge, Target, TrendingUp } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { getRegression } from '@/lib/api'
import type { Regression } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader } from '@/components/common/layout/PageHeader'
import { StatCard, type StatTone } from '@/components/common/layout/StatCard'
import { ImportanceBars, LearnCurve, ParityChart } from '@/components/charts'
import { HowTo } from '@/components/HowTo'
import { Panel } from '@/components/Panel'
import { PageError, PageLoading } from '@/components/PageState'
import ModelStudio from '@/components/ModelStudio'

function rpdTone(rpd: number): StatTone {
  if (rpd >= 3) return 'success'
  if (rpd >= 2.4) return 'info'
  if (rpd >= 1.5) return 'warning'
  return 'danger'
}

function rpdWord(rpd: number): string {
  if (rpd >= 3) return '可用于筛查'
  if (rpd >= 2.4) return '勉强可定量'
  if (rpd >= 1.5) return '只能粗估'
  return '不能用'
}

function rpdBadge(rpd: number) {
  const cls =
    rpd >= 3 ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
      : rpd >= 2.4 ? 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300'
        : rpd >= 1.5 ? 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'
          : 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300'
  return <Badge variant="outline" className={cls}>{rpdWord(rpd)}</Badge>
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
    setReg(null)
    // Next's rewrite proxy drops any single request longer than 30 s, and the
    // first regression call can take longer than that on a loaded box. The API
    // keeps computing and fills its cache, so a retry usually answers in ms.
    ;(async () => {
      let last: unknown = null
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const r = await getRegression(folder, order, refFrac, technique)
          if (alive) { setReg(r); setLoading(false) }
          return
        } catch (e) {
          last = e
          if (!alive) return
          await new Promise((res) => setTimeout(res, 1500))
        }
      }
      if (alive) { setError(String(last)); setLoading(false) }
    })()
    return () => { alive = false }
  }, [folder, order, refFrac, technique])

  const nModels = reg?.models?.length
    ? new Set(reg.models.map((r) => r.name)).size
    : 10

  const header = (
    <PageHeader
      title="预测模型"
      description={nModels + ' 个模型 · 整条曲线与手工特征两套输入 · 留一独立单元交叉验证 · 超参数只在训练折里搜'}
      actions={
        <>
          <Button variant="outline" size="sm" className="rounded-full" asChild>
            <Link href="/models">看分类</Link>
          </Button>
          <Button variant="outline" size="sm" className="rounded-full" asChild>
            <Link href="/data">填浓度</Link>
          </Button>
        </>
      }
    />
  )

  const studio = folder ? <ModelStudio folder={folder} order={order} refFrac={refFrac} /> : null

  if (ctxLoading || (loading && !reg)) {
    return (
      <div className="flex flex-col gap-4 md:gap-6">
        {header}
        {studio}
        <PageLoading label="正在逐个拟合候选模型并做嵌套交叉验证，首次约 20 秒…" />
      </div>
    )
  }
  if (error) {
    return (
      <div className="flex flex-col gap-4 md:gap-6">
        {header}
        {studio}
        <PageError title="后端没有响应" detail={error} />
      </div>
    )
  }
  if (!reg) return null

  if (reg.error) {
    return (
      <div className="flex flex-col gap-4 md:gap-6">
        {header}
        {studio}
        <div className="flex items-start gap-2.5 rounded-[20px] bg-amber-500/10 px-4 py-3.5 ring-1 ring-amber-500/20">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
          <div className="min-w-0 space-y-1">
            <div className="text-xs font-medium">这个文件夹还训练不出预测模型</div>
            <p className="text-[11px] leading-5 text-muted-foreground">{reg.error}</p>
          </div>
        </div>
        <Panel title="缺的是这一列，不是算法" sub="预测模型要的是「同一个条件、不同浓度」">
          <div className="space-y-1.5 text-[11px] leading-5 text-muted-foreground">
            <div className="text-xs font-medium text-foreground">现状</div>
            <div>
              标准点 <span className="font-medium tabular-nums text-foreground">{reg.n_standards ?? 0}</span> 条 ·
              不同浓度 <span className="font-medium tabular-nums text-foreground">{reg.n_levels ?? 0}</span> 个 ·
              独立电极 <span className="font-medium tabular-nums text-foreground">{reg.n_electrodes ?? 0}</span> 支 ·
              批次 <span className="font-medium tabular-nums text-foreground">{reg.n_batches ?? 0}</span> 个
            </div>
            <div className="pt-1">最低门槛：<b className="text-foreground">6 条标准点、3 个不同浓度、3 支独立电极</b>（或 2 个批次）。</div>
            <div className="pt-1">
              一天能做完的最小方案：空白 3 支 + 10 nM 3 支 + 1 µM 3 支 = 9 支电极。
              做完回到「数据」页把浓度填进去，这一页立刻就有东西。
            </div>
          </div>
        </Panel>
      </div>
    )
  }

  const rows = reg.models || []
  const best = reg.best_row
  const pred = reg.best_pred
  const learn = reg.learning?.points || []
  const imp = (reg.importance?.rows || []).map((r) => ({ feature: r.feature, label: r.feature, v: r.v }))
  const last = learn.length ? learn[learn.length - 1] : null

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      {header}
      {studio}

      <section className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
        <StatCard
          label="最佳模型"
          value={reg.best || '—'}
          hint={'输入：' + (reg.best_set || '') + ' · ' + (reg.mode === 'electrode' ? '留一电极' : '留一批次')}
          icon={Target}
          tone="accent"
        />
        <StatCard
          label="R²"
          value={best ? best.r2.toFixed(3) : '—'}
          hint={reg.n_standards + ' 条标准点 · ' + (reg.n_levels || 0) + ' 个浓度 · ' + (reg.decades ?? 0).toFixed(1) + ' 个数量级'}
          icon={TrendingUp}
          tone={best && best.r2 >= 0.95 ? 'success' : 'neutral'}
          delay={0.04}
        />
        <StatCard
          label="误差倍数"
          value={best?.factor ? best.factor.toFixed(2) + '×' : '—'}
          hint={best?.rmse_dex != null ? best.rmse_dex.toFixed(2) + ' dex（预测偏离真值的典型倍数）' : ''}
          icon={Activity}
          delay={0.08}
        />
        <StatCard
          label="RPD"
          value={best ? best.rpd.toFixed(2) : '—'}
          hint={best ? rpdWord(best.rpd) + ' · >3 才算能筛查' : ''}
          icon={Gauge}
          tone={best ? rpdTone(best.rpd) : 'neutral'}
          delay={0.12}
        />
      </section>

      <div className="rounded-[20px] bg-muted px-4 py-3.5">
        <div className="text-xs font-medium">这几个数字怎么读</div>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
          <b className="text-foreground">R²</b> 越接近 1 越好，但它会被浓度范围放大 —— 跨 5 个数量级的 0.94 比跨 1 个数量级的 0.99 更难。
          <b className="ml-1 text-foreground">RPD</b> = 浓度本身的离散度 ÷ 预测误差，&gt;3 才算能用于筛查，&lt;1.5 基本不能用。
          <b className="ml-1 text-foreground">误差倍数</b> 是 10 的对数误差次方：2.7× 意思是「报 100 nM 时真值大概在 37–270 nM 之间」。
        </p>
        <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground/70">
          对照 Food Chem 2025 的镉传感器：R² 0.9904–0.9948、RPD 3.37 —— 人家的标准点是 0.1–200 µM 逐点实测、多支电极重复。
        </p>
      </div>

      <Panel title="模型对比" sub="按 R² 排序 · 同一批标准点、同一套留出规则，只换模型">
        <div className="overflow-hidden rounded-2xl bg-background/60">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>模型</TableHead>
                <TableHead>输入</TableHead>
                <TableHead>R²</TableHead>
                <TableHead>RMSE (dex)</TableHead>
                <TableHead>误差倍数</TableHead>
                <TableHead>RPD</TableHead>
                <TableHead>结论</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((m, i) => (
                <TableRow key={m.set + m.name} className={i === 0 ? 'bg-background/60' : undefined}>
                  <TableCell className="font-medium">
                    <span className="inline-flex items-center gap-2">
                      {m.name}
                      {i === 0 ? (
                        <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">最佳</Badge>
                      ) : null}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{m.set}</TableCell>
                  <TableCell className="tabular-nums">{m.r2.toFixed(3)}</TableCell>
                  <TableCell className="tabular-nums">{m.rmse_dex != null ? m.rmse_dex.toFixed(2) : m.rmse.toFixed(2)}</TableCell>
                  <TableCell className="tabular-nums">{m.factor ? m.factor.toFixed(2) + '×' : '—'}</TableCell>
                  <TableCell className="tabular-nums">{m.rpd.toFixed(2)}</TableCell>
                  <TableCell>{rpdBadge(m.rpd)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div className="mt-3 space-y-1 text-[11px] leading-5 text-muted-foreground">
          <div>
            非线性模型（SVR-RBF / 高斯过程）赢在线性校准开始弯曲的两端；如果线性回归就是最好的，
            说明这批数据还在线性区里 —— 这本身也是一个结论，不必硬上神经网络。
          </div>
          <div>
            BP-ANN 垫底是正常的：{reg.n_standards} 条标准点喂不饱一个神经网络（Food Chem 那篇是几百条曲线）。
            样本少于 100 条时，SVR-RBF / 高斯过程才是合适的选择 —— 它们的参数量由数据自己定。
          </div>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="真值 vs 预测" sub={'虚线是理想线 · ' + (reg.best || '') + ' 留出预测'}>
          {pred && pred.true.length
            ? <ParityChart truth={pred.true} pred={pred.pred} />
            : <div className="py-10 text-center text-[11px] text-muted-foreground">没有预测点</div>}
          <HowTo title="怎么读这张真值-预测散点图" items={[
            <><b>每个点 = 一个标准点曲线</b>。横轴是这个样品<b>已知</b>的浓度（你填进数据表的真值），纵轴是模型<b>只看曲线</b>猜出来的浓度。双对数坐标。</>,
            <>灰色虚线是理想线（猜得完全准）。点越贴近虚线越好；点整体在虚线上方 = 模型系统性高估，在下方 = 系统性低估。</>,
            <>点<b>沿着虚线散开</b>是随机误差（正常，可以靠多测取平均压下去）；点<b>偏离虚线形成一条斜带或弧形</b>说明模型有系统偏差（校准线没选对，或超出线性范围）。</>,
            <>这张图上的点全部来自「留一电极」的预测 —— 也就是模型<b>没见过</b>这支电极。所以它代表的是「换一支新电极还能猜多准」，不是「拟合得多好」。</>,
            <>点很少（十几二十个）时这张图会很「好看」或很「难看」，都是偶然。要看旁边的误差倍数和 RPD，别只看图。</>,
          ]} />
        </Panel>
        <Panel title="学习曲线" sub="再多做几支电极，误差会掉到多少">
          {learn.length ? (
            <>
              <LearnCurve points={learn} />
              <div className="mt-2 text-[11px] leading-5 text-muted-foreground">
                {last
                  ? '训练到 ' + last.n_train + ' 支电极时，留出误差约 ' + last.rmse.toFixed(2) + ' dex（' +
                    Math.pow(10, last.rmse).toFixed(1) + '×）。曲线还在往下走就说明数据不够，走平了就是这批数据的极限。'
                  : ''}
              </div>
            </>
          ) : (
            <div className="py-10 text-center text-[11px] text-muted-foreground">{reg.learning?.error || '独立单元太少，画不出学习曲线'}</div>
          )}
        </Panel>
      </div>

      {imp.length ? (
        <Panel title="哪些特征真正在起作用" sub="打乱这个特征后误差涨多少 · 在留出的电极上算">
          <ImportanceBars rows={imp} />
          <div className="mt-2 text-[11px] leading-5 text-muted-foreground">
            峰电流和比值排在前面是应该的 —— 它们是 MB 的响应本身。如果开路电位、末端电流这类
            「跟浓度无关」的量排得很高，说明模型在吃电极的整体状态，而不是在测链霉素。
          </div>
        </Panel>
      ) : null}

      <Panel title="方法" sub="这一段决定了上面那些数字能不能信">
        <ul className="space-y-1.5 text-[11px] leading-5 text-muted-foreground">
          <li>· 验证单位是<b className="text-foreground">整支电极</b>（或<b className="text-foreground">整个批次</b>），不是单条曲线 —— 同一支电极扫 3 次不算 3 个独立样本。</li>
          <li>· 超参数搜索在<b className="text-foreground">训练折内部</b>完成（嵌套交叉验证），被留出的电极从不参与调参。</li>
          <li>· 标准点跨 {(reg.decades ?? 0).toFixed(1)} 个数量级，模型拟合 log10(C)，所以误差用 dex 表示；跨不到一个数量级时自动改用 C 本身。</li>
          <li>· 两套输入都试：整条基线校正曲线（{reg.meta?.n_points ?? 80} 点，不丢形状信息）与 12 个手工特征（峰高、峰位、电荷、比值）。</li>
          <li>· 高斯过程还会给出每个预测的不确定度，BP-ANN 对应 Food Chem 那篇三种抗生素同时检测的做法。</li>
        </ul>
      </Panel>
    </div>
  )
}
