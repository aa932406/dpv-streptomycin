'use client'

import { useFolder } from '@/lib/folder-context'
import { Badge, Card, Loading, Note, SectionTitle, StatCard, Table, Td } from '@/components/ui'
import { CalibChart } from '@/components/charts'
import { explainFitError, fmtConc, fmtNum } from '@/lib/utils'

export default function CalibPage() {
  const { data, loading, error } = useFolder()
  if (loading) return <Loading />
  if (error) return <Note tone="bad" title="后端没有响应">{error}</Note>
  if (!data) return null

  const fit = data.fit || {}
  const pts = data.calib_points || []
  const verdicts = data.verdicts || []
  const fb = data.fit_batch
  // no single global line, but a per-batch fit exists -> that is the right model here
  const perBatch = !!fb && !fb.error && (fb.batches?.length || 0) > 1

  if (perBatch) {
    const rows = fb!.batches || []
    const lods = rows.map((b) => b.LOD_M).filter((v): v is number => v != null && v > 0)
    const span = lods.length > 1 ? Math.max(...lods) / Math.min(...lods) : 1
    return (
      <div className="space-y-4">
        <Header />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="合并 R²" value={fmtNum(fb!.r2, 3)} sub="各批内部拟合" />
          <StatCard label="全局单线 R²" value={fmtNum(fb!.pooled_r2, 3)} sub="把各批当一批拟合" />
          <StatCard label="留一批次误差" value={fmtNum(fb!.rmse_log_lobo, 2) + ' dex'} sub="换批次后差几个数量级" />
          <StatCard label="批次" value={rows.length} sub="每批自己的截距" />
        </div>

        <Note tone="info" title="这批数据跨多个批次，已自动按批标定">
          每个批次用自己那天的标准点定截距，所有批共用一条斜率 —— 批次之间通常只是整体平移。
          合并 R² 与全局单线 R² 差得越多，说明批次效应越大，越不能拿一条线通吃。
        </Note>


        <Card className="px-5 py-4">
          <SectionTitle sub="每批用自己那天的标准点定截距，斜率共用">各批次校准</SectionTitle>
          <Table head={['批次', '标准点', '浓度数', '截距 a', '斜率 b', 'R²', 'LOD', 'LOQ']}>
            {rows.map((b) => (
              <tr key={b.batch} className="border-b border-[#f2f4f7] last:border-0">
                <Td className="font-medium">{b.batch}</Td>
                <Td className="text-[#667085]">{b.n ?? '—'}</Td>
                <Td className="text-[#667085]">{b.levels ?? '—'}</Td>
                <Td>{fmtNum(b.a, 3)}</Td>
                <Td>{fmtNum(b.b, 3)}</Td>
                <Td>{fmtNum(b.r2, 3)}</Td>
                <Td>{b.LOD_M != null ? fmtConc(b.LOD_M) : (b.note || '—')}</Td>
                <Td className="text-[#98a2b3]">{b.LOQ_M != null ? fmtConc(b.LOQ_M) : '—'}</Td>
              </tr>
            ))}
          </Table>
          {span > 5 ? (
            <p className="mt-2 text-[11.5px] text-[#98a2b3]">
              各批 LOD 相差 {span.toFixed(0)} 倍 —— 空白噪声不一样，不是 bug。同一批里的样品只能跟自己那批的 LOD 比。
            </p>
          ) : null}
        </Card>

        {fit.r2 != null ? (
          <Card className="px-5 py-4">
            <SectionTitle sub="如果强行把各批当一批拟合，就是这个样子">全局单线对照（不该用）</SectionTitle>
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MiniKV label="全局 R²" value={fmtNum(fit.r2, 3)} />
              <MiniKV label="全局斜率" value={fmtNum(fit.b, 3)} />
              <MiniKV label="按批合并 R²" value={fmtNum(fb!.r2, 3)} />
              <MiniKV label="差值" value={fmtNum((fb!.r2 ?? 0) - (fit.r2 ?? 0), 3)} />
            </div>
            <div className="mt-3">
              <CalibChart points={pts} a={fit.a} b={fit.b} />
            </div>
          </Card>
        ) : null}

        <Card className="px-5 py-4">
          <SectionTitle sub="浓度列留空的行被当作未知样品；浓度用自己那一批的截距算">样品浓度</SectionTitle>
          {verdicts.length ? (
            <Table head={['文件', '批次', '分组', '响应', '判定', '浓度', '95% 区间']}>
              {verdicts.map((v) => (
                <tr key={v.file} className="border-b border-[#f2f4f7] last:border-0">
                  <Td className="max-w-[220px] truncate text-[#475467]">{v.file}</Td>
                  <Td className="text-[#667085]">{v.batch || '—'}</Td>
                  <Td className="text-[#667085]">{v.group}</Td>
                  <Td>{fmtNum(v.value, 3)}</Td>
                  <Td>
                    {v.verdict === 'positive' ? <Badge tone="ok">检出</Badge>
                      : v.verdict === 'negative' ? <Badge tone="mute">未检出</Badge>
                        : <Badge tone="warn">无法判定</Badge>}
                  </Td>
                  <Td className="font-medium">{v.verdict === 'positive' ? (v.C_text || fmtConc(v.C)) : '—'}</Td>
                  <Td className="text-[#98a2b3]">{v.C_lo != null ? fmtConc(v.C_lo) + ' ~ ' + fmtConc(v.C_hi) : '—'}</Td>
                </tr>
              ))}
            </Table>
          ) : <Note tone="mute">没有未知样品（浓度列全部填了值）。</Note>}
        </Card>
      </div>
    )
  }

  if (fit.error) {
    return (
      <div className="space-y-4">
        <Header />
        <Note tone="warn" title="这批数据算不出浓度">
          {explainFitError(fit.error)}
          <div className="mt-2 text-[12px]">
            要算出浓度，至少需要 3 个浓度水平、每水平 3 支独立电极、外加 3 支空白。
            缺的是实验设计，不是算法。
          </div>
          <div className="mt-1.5 text-[11px] text-[#98a2b3]">后端原文：{fit.error}</div>
        </Note>
        <Card className="px-5 py-4">
          <SectionTitle sub="把浓度填进数据表后，这里会画出校准曲线">缺什么</SectionTitle>
          <ul className="mt-1 space-y-1.5 text-[12.5px] text-[#475467]">
            <li>· 标准点（已知浓度）：<b>≥ 3 个浓度</b>，建议 10 pM / 100 pM / 1 nM / 10 nM / 100 nM / 1 µM</li>
            <li>· 空白（浓度填 0）：<b>≥ 3 条</b>，用来算 LOD</li>
            <li>· 每水平独立电极：<b>≥ 3 支</b>（同一支电极重复扫描不算）</li>
            <li>· 未知样品：浓度列<b>留空</b>，工具会自动给出浓度和 95% 区间</li>
          </ul>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Header />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="校准 R²" value={fmtNum(fit.r2, 3)} sub={'标准点 ' + (fit.n_std ?? pts.length)} />
        <StatCard label="斜率" value={fmtNum(fit.b, 3)} sub="每十倍浓度" />
        <StatCard label="LOD" value={fit.LOD_M != null ? fmtConc(fit.LOD_M) : '—'} sub="3σ / 斜率" />
        <StatCard label="LOQ" value={fit.LOQ_M != null ? fmtConc(fit.LOQ_M) : '—'} sub="10σ / 斜率" />
      </div>

      <Card className="px-5 py-4">
        <SectionTitle sub={fit.direction === 'signal-off' ? '浓度越高信号越低' : '浓度越高信号越高'}>校准曲线</SectionTitle>
        <CalibChart points={pts} a={fit.a} b={fit.b} />
      </Card>

      <Card className="px-5 py-4">
        <SectionTitle sub="浓度列留空的行被当作未知样品">样品浓度</SectionTitle>
        {verdicts.length ? (
          <Table head={['文件', '分组', '响应', '判定', '浓度', '95% 区间']}>
            {verdicts.map((v) => (
              <tr key={v.file} className="border-b border-[#f2f4f7] last:border-0">
                <Td className="max-w-[240px] truncate text-[#475467]">{v.file}</Td>
                <Td className="text-[#667085]">{v.group}</Td>
                <Td>{fmtNum(v.value, 3)}</Td>
                <Td>
                  {v.verdict === 'positive' ? <Badge tone="ok">检出</Badge>
                    : v.verdict === 'negative' ? <Badge tone="mute">未检出</Badge>
                      : <Badge tone="warn">无法判定</Badge>}
                </Td>
                <Td className="font-medium">{v.verdict === 'positive' ? fmtConc(v.C) : '—'}</Td>
                <Td className="text-[#98a2b3]">{v.C_lo != null ? fmtConc(v.C_lo) + ' ~ ' + fmtConc(v.C_hi) : '—'}</Td>
              </tr>
            ))}
          </Table>
        ) : <Note tone="mute">没有未知样品（浓度列全部填了值）。</Note>}
      </Card>
    </div>
  )
}

function Header() {
  return (
    <div>
      <h1 className="text-[26px] font-semibold tracking-tight text-[#101828]">校准与定量</h1>
      <p className="mt-1 text-[12.5px] text-[#667085]">峰电流对 log10(浓度) 的线性回归 · LOD / LOQ 由空白 3σ 反算</p>
    </div>
  )
}

function MiniKV({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[#eaecf0] px-3 py-2">
      <div className="text-[11.5px] text-[#667085]">{label}</div>
      <div className="mt-0.5 text-[17px] font-semibold leading-none text-[#101828] tnum">{value}</div>
    </div>
  )
}
