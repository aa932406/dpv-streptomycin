'use client'

import { AlertTriangle, CheckCircle2, FolderSearch, Gauge, Users, Layers, ScanLine, XCircle } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { Badge, Card, KeyVal, Loading, Note, SectionTitle, StatCard } from '@/components/ui'
import { CurvesChart, Legend } from '@/components/charts'
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

export default function VerdictPage() {
  const { data, loading, error, folder } = useFolder()

  if (loading) return <Loading />
  if (error) return <Note tone="bad" title="后端没有响应">{error}</Note>
  if (!data || !data.meta || !data.meta.n_curves) {
    return <Note tone="warn" title="这个文件夹里没有可用的 DPV 曲线">换一个数据文件夹试试。</Note>
  }

  const m = data.meta
  const fitErr = data.fit?.error
  const sc = data.screening
  const verdicts = data.verdicts || []
  const fb = data.fit_batch
  // single-line fit failed, but a per-batch fit exists and produced verdicts
  const useBatch = !!fb && !fb.error && (fb.batches?.length || 0) > 1 && verdicts.length > 0

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight text-[#101828]">结论</h1>
        <p className="mt-1 text-[12.5px] text-[#667085]">
          数据文件夹 {m.folder} · {m.n_curves} 条曲线 · {m.n_electrodes} 支独立电极
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="曲线" value={m.n_curves} sub="参与分析的扫描" icon={<ScanLine size={16} />} />
        <StatCard label="独立电极" value={m.n_electrodes} sub="统计上的真实重复数" icon={<Users size={16} />} />
        <StatCard label="分组" value={m.n_groups} sub="实验条件" icon={<Layers size={16} />} />
        <StatCard label="QC 合格" value={m.n_qc + ' / ' + m.n_curves} sub={'内参门槛 ' + fmtNum(m.qc_threshold, 2) + ' µA'} icon={<Gauge size={16} />} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card className="px-5 py-4">
          <SectionTitle sub={fitErr && !useBatch ? '这批数据没有浓度梯度，只能做定性筛查' : useBatch ? '每个样品用自己那一批的截距定量' : ''}>样品判定</SectionTitle>

          {useBatch ? (
            <div className="space-y-2">
              <Note tone="info">
                这批数据跨 {fb.batches?.length || 0} 个批次，单条全局校准线用不了，已改为按批标定：
                每批用自己那天的标准点定截距。合并 R² {fmtNum(fb.r2, 3)}，
                全局单线 R² {fmtNum(fb.pooled_r2, 3)}，留一批次误差 {fmtNum(fb.rmse_log_lobo, 2)} dex。
              </Note>
              {verdicts.map((v) => (
                <div key={v.file} className="flex items-center justify-between rounded-xl border border-[#eaecf0] px-3.5 py-2.5">
                  <div className="flex items-center gap-2">
                    {v.verdict === 'positive'
                      ? <CheckCircle2 size={16} className="text-[#12b76a]" />
                      : v.verdict === 'negative'
                        ? <XCircle size={16} className="text-[#98a2b3]" />
                        : <AlertTriangle size={16} className="text-[#f79009]" />}
                    <div>
                      <div className="text-[13px] font-medium text-[#101828]">{v.file}</div>
                      <div className="text-[11.5px] text-[#98a2b3]">{v.group} · {v.electrode}{v.batch ? ' · 批次 ' + v.batch : ''}</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[13px] font-semibold text-[#101828] tnum">
                      {v.verdict === 'positive' ? (v.C_text || fmtConc(v.C)) : v.verdict === 'negative' ? '未检出' : '无法判定'}
                    </div>
                    {v.verdict === 'positive' && v.C_lo != null ? (
                      <div className="text-[11px] text-[#98a2b3] tnum">
                        95% CI {fmtConc(v.C_lo)} – {fmtConc(v.C_hi)}
                      </div>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          ) : fitErr ? (
            <>
              <Note tone="warn" title={explainFitError(fitErr).title}>
                {explainFitError(fitErr).detail}
              </Note>
              {sc && !sc.error ? (
                <div className="mt-4">
                  <div className="flex items-center gap-2 text-[12.5px] text-[#667085]">
                    定性筛查：
                    <Badge tone="mute">{sc.neg_group}</Badge>
                    对比
                    <Badge tone="info">{sc.pos_group}</Badge>
                    <span className="text-[11.5px] text-[#98a2b3]">
                      {sc.n_neg_elec} 支 / {sc.n_pos_elec} 支独立电极
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <MiniStat label="信号比" value={sc.ratio.toFixed(2) + '×'} />
                    <MiniStat label="电极级 p 值" value={fmtP(sc.p)} />
                    <MiniStat label="效应量 d" value={fmtNum(sc.effect_d, 2)} />
                    <MiniStat label="判别准确率" value={(sc.accuracy * 100).toFixed(0) + '%'} />
                  </div>
                  <div className="mt-3">
                    {!sc.separates ? (
                      <Note tone="bad">
                        这条截断值切不开两组：阴性对照 {sc.false_pos}/{sc.n_neg_elec} 支被判成阳性，
                        阳性样品 {sc.missed}/{sc.n_pos_elec} 支漏检。先把空白 CV 从
                        {' '}{Math.abs(sc.neg_sd / sc.neg_mean * 100).toFixed(0)}% 压到 15–25% 再谈阈值。
                      </Note>
                    ) : (
                      <Note tone="ok">
                        两组完全分开（{sc.n_neg_elec} vs {sc.n_pos_elec} 支电极），截断值
                        {' '}{fmtNum(sc.cutoff, 2)}，可用于定性判断。注意：只能给「检出 / 未检出」，给不出浓度。
                      </Note>
                    )}
                  </div>
                  {sc.p_floor > 0.05 ? (
                    <p className="mt-2 text-[11.5px] text-[#98a2b3]">
                      每组电极数太少，Mann-Whitney 的 p 值最小只能到 {sc.p_floor.toFixed(2)}。
                      每组至少 4 支电极才可能得到 p &lt; 0.05。
                    </p>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : (
            <div className="mt-1 space-y-2">
              {verdicts.length ? verdicts.map((v) => (
                <div key={v.file} className="flex items-center justify-between rounded-xl border border-[#eaecf0] px-3.5 py-2.5">
                  <div className="flex items-center gap-2">
                    {v.verdict === 'positive'
                      ? <CheckCircle2 size={16} className="text-[#12b76a]" />
                      : v.verdict === 'negative'
                        ? <XCircle size={16} className="text-[#98a2b3]" />
                        : <AlertTriangle size={16} className="text-[#f79009]" />}
                    <div>
                      <div className="text-[13px] font-medium text-[#101828]">{v.file}</div>
                      <div className="text-[11.5px] text-[#98a2b3]">{v.group} · {v.electrode}</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[13px] font-semibold text-[#101828] tnum">
                      {v.verdict === 'positive' ? fmtConc(v.C) : v.verdict === 'negative' ? '未检出' : '无法判定'}
                    </div>
                    {v.verdict === 'positive' && v.C_lo != null ? (
                      <div className="text-[11px] text-[#98a2b3] tnum">
                        95% CI {fmtConc(v.C_lo)} – {fmtConc(v.C_hi)}
                      </div>
                    ) : null}
                  </div>
                </div>
              )) : <Note tone="mute">没有待测样品。把浓度列留空的行当作未知样品。</Note>}
            </div>
          )}
        </Card>

        <Card className="px-5 py-4">
          <SectionTitle>体系状态</SectionTitle>
          <p className="-mt-1 mb-1 text-[11.5px] text-[#98a2b3]">这次分析的可信度取决于这几项</p>
          <div className="divide-y divide-[#f2f4f7]">
            <KeyVal k="扫描类型" v={m.technique_cn || '—'} />
            <KeyVal k="扫描窗口" v={m.window[1].toFixed(2) + ' → ' + m.window[0].toFixed(2) + ' V'} />
            <KeyVal k="响应指标" v={m.metric_cn} />
            <KeyVal k="响应方向" v={data.fit?.direction === 'signal-off' ? '信号关闭' : data.fit?.direction === 'signal-on' ? '信号开启' : '—'} />
            <KeyVal k="内参中位数" v={fmtNum(m.qc_median, 2) + ' µA'} />
            <KeyVal k="校准 R²" v={(useBatch ? fb?.r2 : data.fit?.r2) != null ? fmtNum(useBatch ? fb.r2 : data.fit.r2, 3) : '—'} />
            <KeyVal k="LOD" v={useBatch
              ? (fb?.batches?.length ? '各批 ' + fmtConc(Math.min(...fb.batches.map((b) => b.LOD_M ?? Infinity))) + ' 起' : '—')
              : data.fit?.LOD_M != null ? fmtConc(data.fit.LOD_M) : '—'} />
          </div>
        </Card>
      </div>

      <Card className="px-5 py-4">
        <SectionTitle sub={'各条件平均曲线（基线校正，' + m.n_points + ' 点）'}>曲线</SectionTitle>
        <div className="mt-2">
          <Legend series={data.curves.series} />
        </div>
        <CurvesChart grid={data.curves.grid} series={data.curves.series} height={300} />
      </Card>

      {data.errors?.length ? (
        <Card className="px-5 py-4">
          <SectionTitle sub={data.errors.length + ' 个文件没参与分析'}>跳过的文件</SectionTitle>
          <div className="max-h-52 space-y-1 overflow-auto">
            {data.errors.map((e) => (
              <div key={e.file} className="flex gap-2 text-[12px]">
                <FolderSearch size={13} className="mt-0.5 shrink-0 text-[#98a2b3]" />
                <span className="text-[#475467]">{e.file}</span>
                <span className="text-[#98a2b3]">{e.error}</span>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[#eaecf0] px-3 py-2">
      <div className="text-[11.5px] text-[#667085]">{label}</div>
      <div className="mt-0.5 text-[18px] font-semibold leading-none text-[#101828] tnum">{value}</div>
    </div>
  )
}
