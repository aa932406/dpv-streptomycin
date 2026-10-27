'use client'

import { useEffect, useMemo, useState } from 'react'
import { Download, FileJson, FileSpreadsheet, FileText, Image as ImageIcon, RefreshCw, Ruler, Ruler as RulerIcon, Save } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { Badge, Card, Loading, Note, SectionTitle } from '@/components/ui'
import { fitArea, getCvFiles, getElectrode, getPaper, reportUrl, saveElectrode } from '@/lib/api'
import type { CvFile } from '@/lib/api'
import type { AreaFit, Electrode, PaperTable } from '@/lib/types'

type Row = { v: string; ip: string }

function download(name: string, text: string, mime: string) {
  const blob = new Blob([text], { type: mime })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  URL.revokeObjectURL(a.href)
}

function toCsv(rows: { item: string; ours: string; ref: string }[]) {
  const esc = (s: string) => '"' + String(s).replace(/"/g, '""') + '"'
  return ['项目,本次数据,论文对照', ...rows.map(r => [esc(r.item), esc(r.ours), esc(r.ref)].join(','))].join('\n')
}

export default function ExportPage() {
  const { data, loading, error, folder, order, refFrac } = useFolder()

  // ---- paper table
  const [area, setArea] = useState('3mm')
  const [custom, setCustom] = useState('0.0707')
  const [pap, setPap] = useState<PaperTable | null>(null)
  const [busy, setBusy] = useState(false)
  const [perr, setPerr] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  // ---- electrode area (CV)
  const [elec, setElec] = useState<Electrode | null>(null)
  const [model, setModel] = useState('RMMI-C10')
  const [conc, setConc] = useState('1')
  const [nEl, setNEl] = useState('1')
  const [dCoef, setDCoef] = useState('7.6e-6')
  const [rows, setRows] = useState<Row[]>([{ v: '20', ip: '' }, { v: '50', ip: '' }, { v: '100', ip: '' }, { v: '200', ip: '' }])
  const [fit, setFit] = useState<AreaFit | null>(null)
  const [fbusy, setFbusy] = useState(false)
  const [ferr, setFerr] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [cv, setCv] = useState<CvFile[]>([])
  const [cvBusy, setCvBusy] = useState(false)

  useEffect(() => {
    getElectrode()
      .then(e => {
        setElec(e && e.area_cm2 ? e : null)
        if (e?.area_cm2) { setArea('saved'); if (e.model) setModel(e.model) }
      })
      .catch(() => setElec(null))
  }, [])

  const areaArg = area === 'custom' ? custom : area

  useEffect(() => {
    let dead = false
    setCvBusy(true)
    getCvFiles(folder)
      .then(r => { if (!dead) setCv(r.files || []) })
      .catch(() => { if (!dead) setCv([]) })
      .finally(() => { if (!dead) setCvBusy(false) })
    return () => { dead = true }
  }, [folder])

  const cvUsable = cv.filter(f => f.scan_rate_mV_s && f.ipa_uA != null && Number.isFinite(f.ipa_uA))

  function fillFromCv() {
    if (!cvUsable.length) return
    setRows(cvUsable.map(f => ({
      v: String(Math.round(f.scan_rate_mV_s as number)),
      // Randles-Sevcik only cares about the magnitude; a signal-off trace can
      // have its anodic peak below the baseline, which is still a peak.
      ip: Math.abs(f.ipa_uA as number).toFixed(2),
    })))
    setFit(null)
    setFerr(null)
  }

  useEffect(() => {
    let dead = false
    // clearing first matters: without it the previous folder's table stays on
    // screen while the new one is still running the models (~10 s), and the
    // numbers read as if they belonged to the folder named in the header
    setPap(null)
    setBusy(true)
    setPerr(null)
    getPaper(folder, areaArg)
      .then(r => { if (!dead) setPap(r) })
      .catch(e => { if (!dead) { setPap(null); setPerr(String(e.message || e)) } })
      .finally(() => { if (!dead) setBusy(false) })
    return () => { dead = true }
  }, [folder, areaArg, tick])

  const AREAS = useMemo(() => {
    const out: { v: string; t: string }[] = []
    if (elec?.area_cm2) out.push({ v: 'saved', t: '用保存的有效面积 ' + elec.area_cm2.toFixed(4) + ' cm²' })
    out.push({ v: '', t: '不算面积（只报 µA·µM⁻¹）' })
    out.push({ v: '3mm', t: '3 mm 直径 → 0.0707 cm²' })
    out.push({ v: '4mm', t: '4 mm 直径 → 0.1257 cm²' })
    out.push({ v: '2mm', t: '2 mm 直径 → 0.0314 cm²' })
    out.push({ v: 'custom', t: '自定义（填 cm²）' })
    return out
  }, [elec])

  if (loading) return <Loading />
  if (!data && !error) return null
  const hasData = !!data && (data.meta?.n_curves ?? 0) > 0

  const items = [
    { icon: FileText, t: 'report.html', d: '自包含报告，浏览器直接打开' },
    { icon: ImageIcon, t: 'figures/*.png', d: '曲线、PCA、校准、箱线图' },
    { icon: FileSpreadsheet, t: 'tables/*.csv', d: '数据表、组间汇总、ANOVA、模型、文献表' },
    { icon: FileJson, t: 'analysis.json', d: '完整分析结果，可再处理' },
  ]

  const prows = pap?.rows ?? []
  const c = pap?.counts

  async function runFit() {
    setFbusy(true); setFerr(null); setSaved(null)
    try {
      const pts = rows
        .filter(r => r.v.trim() !== '' && r.ip.trim() !== '')
        .map(r => ({ v_mV_s: Number(r.v), ip_uA: Number(r.ip) }))
        .filter(p => Number.isFinite(p.v_mV_s) && Number.isFinite(p.ip_uA))
      const r = await fitArea({
        conc_mM: Number(conc) || 1,
        n: Number(nEl) || 1,
        d_cm2_s: Number(dCoef) || 7.6e-6,
        points: pts,
      })
      setFit(r)
    } catch (e: any) {
      setFerr(String(e.message || e))
    } finally {
      setFbusy(false)
    }
  }

  async function persist() {
    if (!fit?.area_cm2) return
    setFbusy(true); setFerr(null)
    try {
      const r = await saveElectrode({
        area_cm2: fit.area_cm2, model, method: 'randles-sevcik',
        detail: { conc_mM: Number(conc), n: Number(nEl), d_cm2_s: Number(dCoef), r2: fit.r2, points: rows },
      })
      setElec(r.electrode)
      setArea('saved')
      setSaved(r.electrode.area_cm2?.toFixed(4) ?? null)
      setTick(t => t + 1)
    } catch (e: any) {
      setFerr(String(e.message || e))
    } finally {
      setFbusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight text-[#101828]">导出</h1>
        <p className="mt-1 text-[12.5px] text-[#667085]">
          {hasData
            ? '文献格式结果表 + 电极面积 + 报告包 · ' + (data?.meta.n_curves ?? 0) + ' 条曲线 · ' + (data?.meta.n_groups ?? 0) + ' 个分组'
            : '电极面积 + 报告包 · 这个文件夹里没有可分析的 DPV 曲线'}
        </p>
      </div>

      {hasData ? (
      <Card className="px-5 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <SectionTitle>文献格式结果表</SectionTitle>
            <p className="mt-1 text-[12px] text-[#667085]">
              按 Food Chem 论文的七项口径出表：线性范围 / 灵敏度 / LOD / LOQ / R² / RPD / 回收率。
              数据不够的项目写的是原因，不是编出来的数字。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Ruler size={15} className="text-[#98a2b3]" />
            <select
              value={area}
              onChange={e => setArea(e.target.value)}
              className="rounded-lg border border-[#e4e7ec] bg-white px-2.5 py-1.5 text-[12.5px] text-[#344054]"
            >
              {AREAS.map(a => <option key={a.v} value={a.v}>{a.t}</option>)}
            </select>
            {area === 'custom' && (
              <input
                value={custom}
                onChange={e => setCustom(e.target.value)}
                className="w-24 rounded-lg border border-[#e4e7ec] px-2 py-1.5 text-[12.5px] tnum"
                placeholder="cm²"
              />
            )}
          </div>
        </div>

        {c && (
          <p className="mt-3 text-[11.5px] text-[#98a2b3]">
            标准点 {c.n_standards ?? 0} 条 · 空白 {c.n_blanks ?? 0} 条 · 浓度水平 {c.n_levels ?? 0} 个 ·
            独立电极 {c.n_electrodes ?? 0} 支 · 响应指标 {pap?.metric}
            {pap?.area_cm2 ? ' · 面积 ' + pap.area_cm2.toFixed(4) + ' cm²' : ''}
          </p>
        )}

        {perr && <Note tone="bad" title="这张表算不出来">{perr}</Note>}
        {busy && !pap && <p className="mt-3 text-[12px] text-[#98a2b3]">正在算（要跑一遍模型，约 10 秒）…</p>}
        {pap?.error && <Note tone="warn" title="这张表算不出来">{pap.error}</Note>}

        {prows.length > 0 && (
          <>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="border-b border-[#eaecf0] text-left text-[11.5px] text-[#667085]">
                    <th className="py-2 pr-3 font-medium">项目</th>
                    <th className="py-2 pr-3 font-medium">本次数据</th>
                    <th className="py-2 font-medium">论文对照</th>
                  </tr>
                </thead>
                <tbody>
                  {prows.map(r => (
                    <tr key={r.item} className="border-b border-[#f2f4f7] last:border-0">
                      <td className="py-2 pr-3 align-top text-[#475467]">{r.item}</td>
                      <td className="py-2 pr-3 align-top font-medium text-[#101828]">{r.ours}</td>
                      <td className="py-2 align-top text-[#98a2b3]">{r.ref}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {pap?.note && <Note tone="info" title="读这个表要注意">{pap.note.replace(/\*\*/g, '')}</Note>}
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() => download('paper_table_' + folder + '.md', pap!.markdown || '', 'text/markdown;charset=utf-8')}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#e4e7ec] px-3 py-1.5 text-[12.5px] text-[#344054] hover:bg-[#f9fafb]"
              >
                <Download size={14} /> 下载 .md（贴进论文）
              </button>
              <button
                onClick={() => download('paper_table_' + folder + '.csv', toCsv(prows), 'text/csv;charset=utf-8')}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#e4e7ec] px-3 py-1.5 text-[12.5px] text-[#344054] hover:bg-[#f9fafb]"
              >
                <Download size={14} /> 下载 .csv
              </button>
              <button
                onClick={() => setTick(t => t + 1)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#e4e7ec] px-3 py-1.5 text-[12.5px] text-[#344054] hover:bg-[#f9fafb]"
              >
                <RefreshCw size={14} className={busy ? 'animate-spin' : ''} /> 重算
              </button>
            </div>
          </>
        )}
        <p className="mt-3 text-[11.5px] text-[#98a2b3]">
          工作电极面积只影响「µA·µM⁻¹·cm⁻²」这一项。不确定就用下面那张卡量出来，别猜。
        </p>
            </Card>
      ) : (
        <Note tone="warn" title="这个文件夹里没有 DPV 数据">文献格式结果表要读 DPV 曲线；下面这张面积卡不受影响。</Note>
      )}
      

      <Card className="px-5 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <SectionTitle>工作电极有效面积（CV 法）</SectionTitle>
            <p className="mt-1 text-[12px] text-[#667085]">
              丝网印刷碳电极的有效面积比几何面积大 10–30%，猜一个数去算灵敏度，正是论文之间对不上的原因。
              用铁氰化钾做 3–5 个扫速的 CV，填下面两列，按 Randles–Ševčík 反算面积。
            </p>
          </div>
          {elec?.area_cm2 ? (
            <Badge tone="ok">已保存 {elec.area_cm2.toFixed(4)} cm²{elec.measured ? ' · ' + elec.measured : ''}</Badge>
          ) : (
            <Badge tone="mute">还没保存</Badge>
          )}
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          <label className="block">
            <span className="text-[11.5px] text-[#667085]">电极型号</span>
            <input value={model} onChange={e => setModel(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[#e4e7ec] px-2.5 py-1.5 text-[12.5px]" />
          </label>
          <label className="block">
            <span className="text-[11.5px] text-[#667085]">探针浓度 (mM)</span>
            <input value={conc} onChange={e => setConc(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[#e4e7ec] px-2.5 py-1.5 text-[12.5px] tnum" />
          </label>
          <label className="block">
            <span className="text-[11.5px] text-[#667085]">电子数 n</span>
            <input value={nEl} onChange={e => setNEl(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[#e4e7ec] px-2.5 py-1.5 text-[12.5px] tnum" />
          </label>
          <label className="block">
            <span className="text-[11.5px] text-[#667085]">扩散系数 D (cm²/s)</span>
            <input value={dCoef} onChange={e => setDCoef(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[#e4e7ec] px-2.5 py-1.5 text-[12.5px] tnum" />
          </label>
        </div>

        <div className="mt-4 rounded-xl border border-[#eef0f3] bg-[#fbfcfd] px-3.5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[12.5px] font-medium text-[#344054]">从 CV 文件自动读峰电流</div>
              <p className="mt-0.5 text-[11.5px] text-[#667085]">
                {cvBusy ? '正在扫描本文件夹…'
                  : cv.length === 0
                    ? '这个文件夹里没有 CV 文件（.cor 表头为 ID_CV，且电位有正反两个方向）'
                    : '找到 ' + cv.length + ' 条 CV：' + cv.map(f => f.file).join('、')}
              </p>
            </div>
            <button
              onClick={fillFromCv}
              disabled={!cvUsable.length}
              className={'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12.5px] ' +
                (cvUsable.length
                  ? 'border-[#e4e7ec] text-[#344054] hover:bg-white'
                  : 'cursor-not-allowed border-[#f2f4f7] text-[#c4c9d1]')}
            >
              <RefreshCw size={14} /> 填入下面的表
            </button>
          </div>
          {cv.length > 0 && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-[11.5px]">
                <thead>
                  <tr className="text-left text-[#667085]">
                    <th className="py-1 pr-3 font-medium">文件</th>
                    <th className="py-1 pr-3 font-medium">扫速</th>
                    <th className="py-1 pr-3 font-medium">阳极峰</th>
                    <th className="py-1 pr-3 font-medium">阴极峰</th>
                    <th className="py-1 font-medium">ΔEp</th>
                  </tr>
                </thead>
                <tbody>
                  {cv.map(f => (
                    <tr key={f.file} className="border-t border-[#f2f4f7]">
                      <td className="py-1 pr-3 text-[#475467]">{f.file}</td>
                      <td className="py-1 pr-3 tnum text-[#475467]">{f.scan_rate_mV_s?.toFixed(0) ?? '—'} mV/s</td>
                      <td className="py-1 pr-3 tnum text-[#101828]">
                        {f.ipa_uA != null ? f.ipa_uA.toFixed(2) + ' µA' : '—'}
                        {f.epa_v != null && <span className="text-[#98a2b3]"> @ {f.epa_v.toFixed(3)} V</span>}
                      </td>
                      <td className="py-1 pr-3 tnum text-[#101828]">
                        {f.ipc_uA != null ? f.ipc_uA.toFixed(2) + ' µA' : '—'}
                        {f.epc_v != null && <span className="text-[#98a2b3]"> @ {f.epc_v.toFixed(3)} V</span>}
                      </td>
                      <td className="py-1 tnum text-[#475467]">{f.dEp_mV != null ? f.dEp_mV.toFixed(0) + ' mV' : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1.5 text-[11px] text-[#98a2b3]">
                峰电流是扣掉两侧谷点连线（充电电流）之后的高度，不是原始最大值。
                ΔEp 在 60–120 mV 说明电子转移还算快；明显偏大不影响面积，但论文里要写。
              </p>
            </div>
          )}
        </div>

        <div className="mt-4">
          <table className="w-full max-w-md text-[12.5px]">
            <thead>
              <tr className="border-b border-[#eaecf0] text-left text-[11.5px] text-[#667085]">
                <th className="py-1.5 font-medium">扫速 (mV/s)</th>
                <th className="py-1.5 font-medium">峰电流 iₚ (µA)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-[#f2f4f7] last:border-0">
                  <td className="py-1.5 pr-2">
                    <input value={r.v} onChange={e => setRows(rs => rs.map((x, j) => j === i ? { ...x, v: e.target.value } : x))}
                      className="w-24 rounded-lg border border-[#e4e7ec] px-2 py-1 tnum" />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input value={r.ip} onChange={e => setRows(rs => rs.map((x, j) => j === i ? { ...x, ip: e.target.value } : x))}
                      className="w-28 rounded-lg border border-[#e4e7ec] px-2 py-1 tnum" placeholder="从 CHI 读峰电流" />
                  </td>
                  <td className="py-1.5">
                    <button onClick={() => setRows(rs => rs.filter((_, j) => j !== i))}
                      className="text-[11.5px] text-[#98a2b3] hover:text-[#b42318]">删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button onClick={() => setRows(rs => [...rs, { v: '', ip: '' }])}
              className="rounded-lg border border-[#e4e7ec] px-3 py-1.5 text-[12.5px] text-[#344054] hover:bg-[#f9fafb]">+ 加一行</button>
            <button onClick={runFit} disabled={fbusy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#101828] px-3.5 py-1.5 text-[12.5px] font-medium text-white hover:bg-[#1d2939] disabled:opacity-50">
              <RulerIcon size={14} /> {fbusy ? '计算中…' : '算面积'}
            </button>
            {fit?.area_cm2 ? (
              <button onClick={persist} disabled={fbusy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#e4e7ec] px-3 py-1.5 text-[12.5px] text-[#344054] hover:bg-[#f9fafb] disabled:opacity-50">
                <Save size={14} /> 保存为电极面积（自动填进上面的表）
              </button>
            ) : null}
          </div>
        </div>

        {ferr && <Note tone="bad" title="算不出来">{ferr}</Note>}
        {fit?.error && <Note tone="warn" title="算不出来">{fit.error}</Note>}

        {fit?.area_cm2 ? (
          <div className="mt-4">
            <div className="flex flex-wrap items-baseline gap-4">
              <div>
                <div className="text-[11.5px] text-[#667085]">有效面积</div>
                <div className="text-[26px] font-semibold tnum text-[#101828]">{fit.area_cm2.toFixed(4)} cm²</div>
              </div>
              <div>
                <div className="text-[11.5px] text-[#667085]">拟合 R²</div>
                <div className="text-[18px] font-medium tnum text-[#101828]">{fit.r2?.toFixed(4)}</div>
              </div>
              <div>
                <div className="text-[11.5px] text-[#667085]">斜率</div>
                <div className="text-[18px] font-medium tnum text-[#101828]">{fit.slope_uA_per_sqrt_V_s?.toFixed(3)} µA/√(V/s)</div>
              </div>
              {saved && <Badge tone="ok">已保存 {saved} cm²</Badge>}
            </div>
            {fit.resid && fit.resid.length > 0 && (
              <table className="mt-3 text-[12px]">
                <thead>
                  <tr className="border-b border-[#eaecf0] text-left text-[11px] text-[#667085]">
                    <th className="py-1 pr-4 font-medium">扫速 (mV/s)</th>
                    <th className="py-1 pr-4 font-medium">实测 (µA)</th>
                    <th className="py-1 font-medium">拟合 (µA)</th>
                  </tr>
                </thead>
                <tbody>
                  {fit.resid.map(r => (
                    <tr key={r.v_mV_s} className="border-b border-[#f2f4f7] last:border-0">
                      <td className="py-1 pr-4 tnum text-[#475467]">{r.v_mV_s}</td>
                      <td className="py-1 pr-4 tnum text-[#101828]">{r.ip_uA.toFixed(2)}</td>
                      <td className="py-1 tnum text-[#98a2b3]">{r.pred_uA.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {(fit.warnings ?? []).map((w, i) => (
              <Note key={i} tone="warn" title="先别急着用这个数">{w}</Note>
            ))}
          </div>
        ) : null}

        <details className="mt-4 rounded-xl border border-[#eef0f3] bg-[#fbfcfd] px-4 py-3">
          <summary className="cursor-pointer text-[12.5px] font-medium text-[#344054]">怎么测（照做就行）</summary>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-[12px] text-[#475467]">
            <li>配 1 mM K₃[Fe(CN)₆] + 0.1 M KCl（现配，避光；铁氰化钾见光会慢慢变绿）。</li>
            <li>同一支电极，扫 20 / 50 / 100 / 200 mV/s 的 CV，电位窗 −0.2 ~ +0.6 V（vs Ag/AgCl）。</li>
            <li>每个扫速读**阳极峰电流**（正向扫描那个峰，约 +0.2 V），单位 µA，减掉基线。</li>
            <li>填进上表 → 算面积 → 保存。之后所有灵敏度都自动用这个面积。</li>
            <li>换一批电极就重测一次：不同批的印刷碳层厚度不一样，面积会差 10% 以上。</li>
          </ol>
        </details>
      </Card>

      <Card className="px-5 py-5">
        <SectionTitle>报告包</SectionTitle>
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map(({ icon: Icon, t, d }) => (
            <div key={t} className="flex items-start gap-2.5 rounded-xl border border-[#eaecf0] px-3 py-2.5">
              <Icon size={15} className="mt-0.5 text-[#98a2b3]" />
              <div>
                <div className="text-[12.5px] font-medium text-[#101828]">{t}</div>
                <div className="text-[11.5px] text-[#98a2b3]">{d}</div>
              </div>
            </div>
          ))}
        </div>
        <a
          href={reportUrl(folder, order, refFrac)}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-[#101828] px-4 py-2 text-[13px] font-medium text-white hover:bg-[#1d2939]"
        >
          <Download size={15} />
          下载报告包（zip）
        </a>
        <p className="mt-3 text-[11.5px] text-[#98a2b3]">
          图内文字是英文（服务器上没有中文字体），表格与报告正文是中文。zip 里也带一份 paper_table.md。
        </p>
      </Card>
    </div>
  )
}
