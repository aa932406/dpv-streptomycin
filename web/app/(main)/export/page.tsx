'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  AlertTriangle, Check, Download, FileJson, FileSpreadsheet, FileText,
  Image as ImageIcon, RefreshCw, Ruler, Save, Trash2,
} from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader } from '@/components/common/layout/PageHeader'
import { fitArea, getCvFiles, getElectrode, getPaper, reportUrl, saveElectrode } from '@/lib/api'
import type { CvFile } from '@/lib/api'
import type { AreaFit, Electrode, PaperTable } from '@/lib/types'
import { Panel } from '@/components/Panel'
import { PageLoading } from '@/components/PageState'

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

function Warn({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-3 flex items-start gap-2.5 rounded-2xl bg-amber-500/10 px-3.5 py-2.5 ring-1 ring-amber-500/20">
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
      <div className="min-w-0 space-y-0.5 text-[11px] leading-5">
        <div className="font-medium">{title}</div>
        <div className="text-muted-foreground">{children}</div>
      </div>
    </div>
  )
}

export default function ExportPage() {
  const { data, loading, folder, order, refFrac } = useFolder()

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

  if (loading) return <PageLoading />
  if (!data) return null
  const hasData = (data.meta?.n_curves ?? 0) > 0

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
    <div className="flex flex-col gap-4 md:gap-6">
      <PageHeader
        title="导出"
        description={hasData
          ? '文献格式结果表 + 电极面积 + 报告包 · ' + (data.meta.n_curves ?? 0) + ' 条曲线 · ' + (data.meta.n_groups ?? 0) + ' 个分组'
          : '电极面积 + 报告包 · 这个文件夹里没有可分析的 DPV 曲线'}
        actions={
          <>
            <Button variant="outline" size="sm" className="rounded-full" asChild>
              <Link href="/calib">看校准</Link>
            </Button>
            <Button size="sm" className="rounded-full" asChild>
              <a href={reportUrl(folder, order, refFrac)}>
                <Download className="size-3.5" />
                下载报告包
              </a>
            </Button>
          </>
        }
      />

      {hasData ? (
        <Panel
          title="文献格式结果表"
          sub="按 Food Chem 论文的七项口径出表：线性范围 / 灵敏度 / LOD / LOQ / R² / RPD / 回收率"
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Ruler className="size-3.5 text-muted-foreground" />
              <Select value={area} onValueChange={setArea}>
                <SelectTrigger size="sm" className="w-[220px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {AREAS.map(a => <SelectItem key={a.v} value={a.v}>{a.t}</SelectItem>)}
                </SelectContent>
              </Select>
              {area === 'custom' ? (
                <Input
                  className="h-8 w-24 text-xs"
                  value={custom}
                  onChange={e => setCustom(e.target.value)}
                  placeholder="cm²"
                />
              ) : null}
            </div>
          }
        >
          <p className="text-[11px] leading-5 text-muted-foreground">
            数据不够的项目写的是原因，不是编出来的数字。
          </p>

          {c ? (
            <p className="mt-1.5 text-[10px] text-muted-foreground/70">
              标准点 {c.n_standards ?? 0} 条 · 空白 {c.n_blanks ?? 0} 条 · 浓度水平 {c.n_levels ?? 0} 个 ·
              独立电极 {c.n_electrodes ?? 0} 支 · 响应指标 {pap?.metric}
              {pap?.area_cm2 ? ' · 面积 ' + pap.area_cm2.toFixed(4) + ' cm²' : ''}
            </p>
          ) : null}

          {perr ? <Warn title="这张表算不出来">{perr}</Warn> : null}
          {busy && !pap ? <p className="mt-3 text-[11px] text-muted-foreground">正在算（要跑一遍模型，约 10 秒）…</p> : null}
          {pap?.error ? <Warn title="这张表算不出来">{pap.error}</Warn> : null}

          {prows.length > 0 ? (
            <>
              <div className="mt-3 overflow-hidden rounded-2xl bg-background/60">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>项目</TableHead>
                      <TableHead>本次数据</TableHead>
                      <TableHead>论文对照</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {prows.map(r => (
                      <TableRow key={r.item}>
                        <TableCell className="align-top text-muted-foreground">{r.item}</TableCell>
                        <TableCell className="align-top font-medium">{r.ours}</TableCell>
                        <TableCell className="align-top text-muted-foreground/70">{r.ref}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {pap?.note ? <Warn title="读这个表要注意">{pap.note.replace(/\*\*/g, '')}</Warn> : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant="outline" size="sm" className="rounded-full"
                  onClick={() => download('paper_table_' + folder + '.md', pap!.markdown || '', 'text/markdown;charset=utf-8')}
                >
                  <Download className="size-3.5" /> 下载 .md（贴进论文）
                </Button>
                <Button
                  variant="outline" size="sm" className="rounded-full"
                  onClick={() => download('paper_table_' + folder + '.csv', toCsv(prows), 'text/csv;charset=utf-8')}
                >
                  <Download className="size-3.5" /> 下载 .csv
                </Button>
                <Button variant="outline" size="sm" className="rounded-full" onClick={() => setTick(t => t + 1)}>
                  <RefreshCw className={'size-3.5' + (busy ? ' animate-spin' : '')} /> 重算
                </Button>
              </div>
            </>
          ) : null}
          <p className="mt-3 text-[10px] text-muted-foreground/70">
            工作电极面积只影响「µA·µM⁻¹·cm⁻²」这一项。不确定就用下面那张卡量出来，别猜。
          </p>
        </Panel>
      ) : (
        <Warn title="这个文件夹里没有 DPV 数据">文献格式结果表要读 DPV 曲线；下面这张面积卡不受影响。</Warn>
      )}

      <Panel
        title="工作电极有效面积（CV 法）"
        sub="丝网印刷碳电极的有效面积比几何面积大 10–30%，猜一个数去算灵敏度，正是论文之间对不上的原因"
        actions={elec?.area_cm2 ? (
          <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
            已保存 {elec.area_cm2.toFixed(4)} cm²{elec.measured ? ' · ' + elec.measured : ''}
          </Badge>
        ) : <Badge variant="secondary">还没保存</Badge>}
      >
        <p className="text-[11px] leading-5 text-muted-foreground">
          用铁氰化钾做 3–5 个扫速的 CV，填下面两列，按 Randles–Ševčík 反算面积。
        </p>

        <div className="mt-3 grid gap-2 sm:grid-cols-4">
          <label className="block">
            <span className="text-[10px] text-muted-foreground">电极型号</span>
            <Input className="mt-1 h-8 text-xs" value={model} onChange={e => setModel(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-[10px] text-muted-foreground">探针浓度 (mM)</span>
            <Input className="mt-1 h-8 text-xs tabular-nums" value={conc} onChange={e => setConc(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-[10px] text-muted-foreground">电子数 n</span>
            <Input className="mt-1 h-8 text-xs tabular-nums" value={nEl} onChange={e => setNEl(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-[10px] text-muted-foreground">扩散系数 D (cm²/s)</span>
            <Input className="mt-1 h-8 text-xs tabular-nums" value={dCoef} onChange={e => setDCoef(e.target.value)} />
          </label>
        </div>

        <div className="mt-3 rounded-2xl bg-background/60 px-3.5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-medium">从 CV 文件自动读峰电流</div>
              <p className="mt-0.5 text-[10px] leading-5 text-muted-foreground">
                {cvBusy ? '正在扫描本文件夹…'
                  : cv.length === 0
                    ? '这个文件夹里没有 CV 文件（.cor 表头为 ID_CV，且电位有正反两个方向）'
                    : '找到 ' + cv.length + ' 条 CV：' + cv.map(f => f.file).join('、')}
              </p>
            </div>
            <Button
              variant="outline" size="sm" className="h-8 rounded-full px-3 text-[11px]"
              onClick={fillFromCv}
              disabled={!cvUsable.length}
            >
              <RefreshCw className="size-3" /> 填入下面的表
            </Button>
          </div>
          {cv.length > 0 ? (
            <div className="mt-2 overflow-hidden rounded-xl bg-muted/40">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-8">文件</TableHead>
                    <TableHead className="h-8">扫速</TableHead>
                    <TableHead className="h-8">阳极峰</TableHead>
                    <TableHead className="h-8">阴极峰</TableHead>
                    <TableHead className="h-8">ΔEp</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {cv.map(f => (
                    <TableRow key={f.file}>
                      <TableCell className="py-1 text-[10px] text-muted-foreground">{f.file}</TableCell>
                      <TableCell className="py-1 text-[10px] tabular-nums text-muted-foreground">{f.scan_rate_mV_s?.toFixed(0) ?? '—'} mV/s</TableCell>
                      <TableCell className="py-1 text-[10px] tabular-nums">
                        {f.ipa_uA != null ? f.ipa_uA.toFixed(2) + ' µA' : '—'}
                        {f.epa_v != null ? <span className="text-muted-foreground/70"> @ {f.epa_v.toFixed(3)} V</span> : null}
                      </TableCell>
                      <TableCell className="py-1 text-[10px] tabular-nums">
                        {f.ipc_uA != null ? f.ipc_uA.toFixed(2) + ' µA' : '—'}
                        {f.epc_v != null ? <span className="text-muted-foreground/70"> @ {f.epc_v.toFixed(3)} V</span> : null}
                      </TableCell>
                      <TableCell className="py-1 text-[10px] tabular-nums text-muted-foreground">{f.dEp_mV != null ? f.dEp_mV.toFixed(0) + ' mV' : '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="px-2 py-1.5 text-[10px] leading-5 text-muted-foreground/70">
                峰电流是扣掉两侧谷点连线（充电电流）之后的高度，不是原始最大值。
                ΔEp 在 60–120 mV 说明电子转移还算快；明显偏大不影响面积，但论文里要写。
              </p>
            </div>
          ) : null}
        </div>

        <div className="mt-3">
          <div className="overflow-hidden rounded-2xl bg-background/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="h-8">扫速 (mV/s)</TableHead>
                  <TableHead className="h-8">峰电流 iₚ (µA)</TableHead>
                  <TableHead className="h-8 w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="py-1">
                      <Input
                        className="h-7 w-24 text-xs tabular-nums"
                        value={r.v}
                        onChange={e => setRows(rs => rs.map((x, j) => j === i ? { ...x, v: e.target.value } : x))}
                      />
                    </TableCell>
                    <TableCell className="py-1">
                      <Input
                        className="h-7 w-28 text-xs tabular-nums"
                        value={r.ip}
                        placeholder="从 CHI 读峰电流"
                        onChange={e => setRows(rs => rs.map((x, j) => j === i ? { ...x, ip: e.target.value } : x))}
                      />
                    </TableCell>
                    <TableCell className="py-1">
                      <Button
                        variant="ghost" size="sm"
                        className="h-7 rounded-full px-2 text-[10px] text-muted-foreground hover:text-red-600"
                        onClick={() => setRows(rs => rs.filter((_, j) => j !== i))}
                      >
                        <Trash2 className="size-3" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              variant="outline" size="sm" className="h-8 rounded-full px-3 text-[11px]"
              onClick={() => setRows(rs => [...rs, { v: '', ip: '' }])}
            >
              + 加一行
            </Button>
            <Button size="sm" className="h-8 rounded-full px-3 text-[11px]" onClick={runFit} disabled={fbusy}>
              <Ruler className="size-3" /> {fbusy ? '计算中…' : '算面积'}
            </Button>
            {fit?.area_cm2 ? (
              <Button variant="outline" size="sm" className="h-8 rounded-full px-3 text-[11px]" onClick={persist} disabled={fbusy}>
                <Save className="size-3" /> 保存为电极面积（自动填进上面的表）
              </Button>
            ) : null}
          </div>
        </div>

        {ferr ? <Warn title="算不出来">{ferr}</Warn> : null}
        {fit?.error ? <Warn title="算不出来">{fit.error}</Warn> : null}

        {fit?.area_cm2 ? (
          <div className="mt-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div className="rounded-2xl bg-background/60 px-3 py-2">
                <div className="text-[10px] text-muted-foreground">有效面积</div>
                <div className="mt-0.5 text-lg font-semibold tabular-nums">{fit.area_cm2.toFixed(4)} cm²</div>
              </div>
              <div className="rounded-2xl bg-background/60 px-3 py-2">
                <div className="text-[10px] text-muted-foreground">拟合 R²</div>
                <div className="mt-0.5 text-lg font-semibold tabular-nums">{fit.r2?.toFixed(4)}</div>
              </div>
              <div className="rounded-2xl bg-background/60 px-3 py-2 sm:col-span-2">
                <div className="text-[10px] text-muted-foreground">斜率</div>
                <div className="mt-0.5 text-lg font-semibold tabular-nums">{fit.slope_uA_per_sqrt_V_s?.toFixed(3)} µA/√(V/s)</div>
              </div>
            </div>
            {saved ? (
              <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[10px] text-emerald-700 ring-1 ring-emerald-500/20 dark:text-emerald-300">
                <Check className="size-3" /> 已保存 {saved} cm²
              </div>
            ) : null}
            {fit.resid && fit.resid.length > 0 ? (
              <div className="mt-2 overflow-hidden rounded-2xl bg-background/60">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="h-8">扫速 (mV/s)</TableHead>
                      <TableHead className="h-8">实测 (µA)</TableHead>
                      <TableHead className="h-8">拟合 (µA)</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {fit.resid.map(r => (
                      <TableRow key={r.v_mV_s}>
                        <TableCell className="py-1 text-[10px] tabular-nums text-muted-foreground">{r.v_mV_s}</TableCell>
                        <TableCell className="py-1 text-[10px] tabular-nums">{r.ip_uA.toFixed(2)}</TableCell>
                        <TableCell className="py-1 text-[10px] tabular-nums text-muted-foreground/70">{r.pred_uA.toFixed(2)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : null}
            {(fit.warnings ?? []).map((w, i) => <Warn key={i} title="先别急着用这个数">{w}</Warn>)}
          </div>
        ) : null}

        <details className="group mt-3 rounded-2xl bg-background/60 px-3.5 py-3">
          <summary className="cursor-pointer select-none text-[11px] font-medium">怎么测（照做就行）</summary>
          <ol className="mt-2 list-decimal space-y-1 pl-4 text-[11px] leading-5 text-muted-foreground">
            <li>配 1 mM K₃[Fe(CN)₆] + 0.1 M KCl（现配，避光；铁氰化钾见光会慢慢变绿）。</li>
            <li>同一支电极，扫 20 / 50 / 100 / 200 mV/s 的 CV，电位窗 −0.2 ~ +0.6 V（vs Ag/AgCl）。</li>
            <li>每个扫速读阳极峰电流（正向扫描那个峰，约 +0.2 V），单位 µA，减掉基线。</li>
            <li>填进上表 → 算面积 → 保存。之后所有灵敏度都自动用这个面积。</li>
            <li>换一批电极就重测一次：不同批的印刷碳层厚度不一样，面积会差 10% 以上。</li>
          </ol>
        </details>
      </Panel>

      <Panel title="报告包" sub="一个 zip，图、表、报告、原始数据都在里面">
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map(({ icon: Icon, t, d }) => (
            <div key={t} className="flex items-start gap-2.5 rounded-2xl bg-background/60 px-3 py-2.5">
              <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              <div>
                <div className="text-xs font-medium">{t}</div>
                <div className="text-[10px] text-muted-foreground">{d}</div>
              </div>
            </div>
          ))}
        </div>
        <Button size="sm" className="mt-3 rounded-full" asChild>
          <a href={reportUrl(folder, order, refFrac)}>
            <Download className="size-3.5" />
            下载报告包（zip）
          </a>
        </Button>
        <p className="mt-2 text-[10px] leading-5 text-muted-foreground/70">
          图内文字是英文（服务器上没有中文字体），表格与报告正文是中文。zip 里也带一份 paper_table.md。
        </p>
      </Panel>
    </div>
  )
}
