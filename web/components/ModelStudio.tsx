'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, Download, FlaskConical, Trash2, Upload } from 'lucide-react'
import { deleteModel, listModels, modelDownloadUrl, predictSamples, trainModel, trainStatus } from '@/lib/api'
import type { PredictResult, PredictRow, SavedModel, TrainResult } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { HowTo } from '@/components/HowTo'
import { Panel } from '@/components/Panel'

const UNITS: [string, number][] = [['M', 1], ['mM', 1e-3], ['µM', 1e-6], ['nM', 1e-9], ['pM', 1e-12]]

function fmtConc(c?: number | null): string {
  if (c === null || c === undefined || !Number.isFinite(c)) return '—'
  for (const [u, s] of UNITS) if (c >= s * 0.999) return (c / s).toPrecision(3) + ' ' + u
  return (c / 1e-12).toPrecision(3) + ' pM'
}

function errText(e: unknown): string {
  const raw = String((e as Error)?.message ?? e)
  try {
    const j = JSON.parse(raw) as { detail?: string }
    if (j && j.detail) return String(j.detail)
  } catch {
    /* not JSON: fall through to the raw text */
  }
  return raw
}

async function toB64(f: File): Promise<string> {
  const bytes = new Uint8Array(await f.arrayBuffer())
  let s = ''
  const step = 0x8000
  for (let i = 0; i < bytes.length; i += step) {
    s += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + step)))
  }
  return btoa(s)
}

function Warn({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 rounded-2xl bg-amber-500/10 px-3.5 py-2.5 ring-1 ring-amber-500/20">
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
      <div className="min-w-0 space-y-0.5 text-[11px] leading-5">
        <div className="font-medium">{title}</div>
        <div className="break-words text-muted-foreground">{children}</div>
      </div>
    </div>
  )
}

export default function ModelStudio({ folder, order, refFrac }: { folder: string; order: number; refFrac: number }) {
  const [models, setModels] = useState<SavedModel[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [fmt, setFmt] = useState<'joblib' | 'pkl'>('joblib')
  const [training, setTraining] = useState(false)
  const [waited, setWaited] = useState(0)
  const alive = useRef(true)
  const [trainRes, setTrainRes] = useState<TrainResult | null>(null)
  const [trainErr, setTrainErr] = useState<string | null>(null)

  const [sel, setSel] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [pred, setPred] = useState<PredictResult | null>(null)
  const [predErr, setPredErr] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoadError(null)
    setLoading(true)
    try {
      const r = await listModels()
      setModels(r.models || [])
      setSel((cur) => cur || (r.models && r.models[0] ? r.models[0].name : ''))
    } catch (e) {
      setLoadError(errText(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { reload() }, [reload])
  useEffect(() => () => { alive.current = false }, [])

  async function onTrain() {
    setTraining(true)
    setTrainErr(null)
    setTrainRes(null)
    setWaited(0)
    const t0 = Date.now()
    try {
      // Training takes tens of seconds to minutes, and Next's rewrite proxy cuts
      // any single request at 30 s. So the server starts a background job and we
      // poll a cheap status endpoint instead of holding one long connection.
      const start = await trainModel({ folder, order, ref_frac: refFrac, format: fmt, target: '链霉素' })
      for (let i = 0; i < 900 && alive.current; i++) {
        await new Promise((r) => setTimeout(r, 2000))
        if (!alive.current) return
        setWaited(Math.round((Date.now() - t0) / 1000))
        const s = await trainStatus(start.job_id)
        if (s.state === 'done') {
          setTrainRes(s as unknown as TrainResult)
          await reload()
          if (s.name) setSel(s.name)
          return
        }
        if (s.state === 'error') {
          setTrainErr(s.error ?? '训练失败')
          return
        }
      }
      if (alive.current) setTrainErr('训练超过 30 分钟没有结果，去服务器上看一眼 uvicorn 日志。')
    } catch (e) {
      setTrainErr(errText(e))
    } finally {
      if (alive.current) setTraining(false)
    }
  }

  async function onDelete(name: string) {
    try {
      await deleteModel(name)
      setPred(null)
      await reload()
    } catch (e) {
      setPredErr(errText(e))
    }
  }

  async function onPredict() {
    if (!sel || files.length === 0) return
    setBusy(true)
    setPredErr(null)
    setPred(null)
    try {
      const payload: { name: string; b64: string }[] = []
      for (const f of files) payload.push({ name: f.name, b64: await toB64(f) })
      setPred(await predictSamples(sel, payload))
    } catch (e) {
      setPredErr(errText(e))
    } finally {
      setBusy(false)
    }
  }

  function saveCsv(rows: PredictRow[]) {
    const head = ['file', 'detected', 'pred_M', 'lo_M', 'hi_M', 'group', 'I_MB', 'I_ref', 'ratio']
    const body = rows.map((r) => [r.file, r.detected === null ? '' : String(r.detected),
      r.pred_M, r.lo_M, r.hi_M, r.group ?? '', r.I_MB ?? '', r.I_ref ?? '', r.ratio ?? ''].join(','))
    const csv = '\ufeff' + head.join(',') + '\n' + body.join('\n') + '\n'
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'predictions_' + sel + '.csv'
    a.click()
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title="训练并下载模型"
        sub="把当前文件夹的模型真的存成一个文件 · 约 20 秒（9 个算法 × 2 套输入）"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Select value={fmt} onValueChange={(v) => setFmt(v === 'pkl' ? 'pkl' : 'joblib')} disabled={training}>
            <SelectTrigger size="sm" className="w-[300px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="joblib">.joblib（推荐，numpy 数组单独存，文件更小）</SelectItem>
              <SelectItem value="pkl">.pkl（纯 pickle，任何 Python 都能 pickle.load）</SelectItem>
            </SelectContent>
          </Select>
          <Button size="sm" className="h-8 rounded-full px-3.5 text-[11px]" onClick={onTrain} disabled={training || !folder}>
            <FlaskConical className="size-3" />
            {training ? '正在训练… ' + waited + ' s' : '训练并下载模型'}
          </Button>
          <span className="text-[10px] leading-5 text-muted-foreground">
            训练用的是「数据」页里填的浓度；没有浓度梯度时会直接告诉你缺什么，不会存一个假模型。
          </span>
        </div>

        {trainErr ? <div className="mt-2"><Warn title="这个文件夹现在还训练不出模型">{trainErr}</Warn></div> : null}

        {trainRes ? (
          <div className="mt-2 rounded-2xl bg-background/60 p-3">
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                <Check className="size-3" /> 已保存
              </Badge>
              <span className="font-medium">{trainRes.name}.{fmt}</span>
              <span className="text-muted-foreground">
                {trainRes.model.model} · {trainRes.model.input === 'curves' ? '整条曲线' : '手工特征'} ·
                R² {(trainRes.model.r2 ?? 0).toFixed(3)} · RPD {(trainRes.model.rpd ?? 0).toFixed(2)} ·
                {(trainRes.model.size_kb ?? 0).toFixed(1)} KB
              </span>
              <Button variant="outline" size="sm" className="h-7 rounded-full px-2.5 text-[10px]" asChild>
                <a href={modelDownloadUrl(trainRes.name)}>
                  <Download className="size-3" /> 下载 {trainRes.name}.{fmt}
                </a>
              </Button>
            </div>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-xl bg-muted/50 p-2.5 text-[10px] leading-5 text-muted-foreground">
              {trainRes.log.join('\n')}
            </pre>
          </div>
        ) : null}
      </Panel>

      <Panel title="模型仓库" sub={loading ? '正在读取…' : models.length + ' 个模型 · 存在服务器的 models/ 目录'}>
        {loadError ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-red-500/10 px-3.5 py-3 text-[11px] ring-1 ring-red-500/20">
            <span className="break-words text-red-700 dark:text-red-300">模型列表读取失败：{loadError}</span>
            <Button variant="outline" size="sm" className="h-7 px-2.5 text-[10px]" onClick={reload} disabled={loading}>
              {loading ? '正在重试…' : '重试'}
            </Button>
          </div>
        ) : models.length === 0 ? (
          <div className="rounded-2xl bg-background/60 py-8 text-center text-[11px] text-muted-foreground">
            还没有训练过模型。点上面的「训练并下载模型」，或者换到有浓度梯度的文件夹（演示数据）再试。
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl bg-background/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>模型文件</TableHead>
                  <TableHead>算法</TableHead>
                  <TableHead>输入</TableHead>
                  <TableHead>R²</TableHead>
                  <TableHead>RPD</TableHead>
                  <TableHead>大小</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {models.map((m) => (
                  <TableRow key={m.name} className={m.name === sel ? 'bg-background/60' : undefined}>
                    <TableCell className="font-medium">
                      {m.name}<span className="ml-1 text-[10px] text-muted-foreground">.{m.format}</span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{m.model || '—'}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {m.input === 'curves' ? '整条曲线' : m.input === 'features' ? '手工特征' : '—'}
                    </TableCell>
                    <TableCell className="tabular-nums">{m.r2 !== undefined && m.r2 !== null ? m.r2.toFixed(3) : '—'}</TableCell>
                    <TableCell className="tabular-nums">{m.rpd !== undefined && m.rpd !== null ? m.rpd.toFixed(2) : '—'}</TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">{(m.size_kb ?? 0).toFixed(1)} KB</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <Button variant="outline" size="sm" className="h-7 rounded-full px-2.5 text-[10px]" asChild>
                          <a href={modelDownloadUrl(m.name)}><Download className="size-3" /> 下载</a>
                        </Button>
                        <Button
                          variant="ghost" size="sm"
                          className="h-7 rounded-full px-2 text-[10px] text-muted-foreground hover:text-red-600"
                          onClick={() => onDelete(m.name)}
                        >
                          <Trash2 className="size-3" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Panel>

      <Panel title="用模型预测新样品" sub="选一个模型，把新测的 .cor 拖进来 —— 不用碰命令行">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={sel} onValueChange={setSel}>
            <SelectTrigger size="sm" className="w-[240px]"><SelectValue placeholder="选模型…" /></SelectTrigger>
            <SelectContent>
              {models.map((m) => <SelectItem key={m.name} value={m.name}>{m.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <input
            type="file"
            multiple
            accept=".cor,.txt"
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
            className="text-[11px] text-muted-foreground file:mr-2 file:h-8 file:rounded-full file:border file:border-border file:bg-background file:px-3 file:text-[10px] file:font-medium file:text-foreground"
          />
          <Button
            size="sm" className="h-8 rounded-full px-3.5 text-[11px]"
            onClick={onPredict}
            disabled={busy || !sel || files.length === 0}
          >
            <Upload className="size-3" />
            {busy ? '正在算…' : '预测' + (files.length ? '（' + files.length + ' 个文件）' : '')}
          </Button>
          {pred && pred.rows.length ? (
            <Button variant="outline" size="sm" className="h-8 rounded-full px-3 text-[11px]" onClick={() => saveCsv(pred.rows)}>
              <Download className="size-3" /> 下载 CSV
            </Button>
          ) : null}
        </div>

        {predErr ? <div className="mt-2"><Warn title="预测失败">{predErr}</Warn></div> : null}

        {pred ? (
          <>
            <div className="mt-2 overflow-hidden rounded-2xl bg-background/60">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>文件</TableHead>
                    <TableHead>判定</TableHead>
                    <TableHead>预测浓度</TableHead>
                    <TableHead>可能的范围</TableHead>
                    <TableHead>I_MB</TableHead>
                    <TableHead>I_ref</TableHead>
                    <TableHead>比值</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pred.rows.map((r) => (
                    <TableRow key={r.file}>
                      <TableCell className="font-medium">{r.file}</TableCell>
                      <TableCell>
                        {r.detected === false
                          ? <Badge variant="secondary">未检出</Badge>
                          : r.detected === true
                            ? <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">检出</Badge>
                            : <Badge variant="outline">—</Badge>}
                      </TableCell>
                      <TableCell className="font-semibold tabular-nums">{r.detected === false ? '—' : fmtConc(r.pred_M)}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {r.detected === false ? '—' : fmtConc(r.lo_M) + ' – ' + fmtConc(r.hi_M)}
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{r.I_MB !== undefined && r.I_MB !== null ? r.I_MB.toFixed(2) : '—'}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{r.I_ref !== undefined && r.I_ref !== null ? r.I_ref.toFixed(2) : '—'}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{r.ratio !== undefined && r.ratio !== null ? r.ratio.toFixed(3) : '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {pred.bad.length ? (
              <div className="mt-2"><Warn title={pred.bad.length + ' 个文件没算出来'}>{pred.bad.map((b) => b.file + '：' + b.error).join('；')}</Warn></div>
            ) : null}
            <p className="mt-2 text-[10px] leading-5 text-muted-foreground/70">
              「未检出」是用模型卡里存的空白分布（3 SD）判的，不是回归算出来的 —— 回归只见过有浓度的样品，
              它没法自己说「这里什么都没有」。范围是 ±1 个交叉验证误差（约 {(pred.model.factor ?? 1).toFixed(1)} 倍）。
            </p>
          </>
        ) : null}

        <HowTo title="模型到底怎么「调用」" items={[
          <>这一页就是调用：选模型 → 上传 .cor → 出浓度。<b>不需要命令行</b>。上传的文件只在内存里算，不落盘。</>,
          <>自动化 / 批量：<code className="rounded bg-muted px-1">POST /api/predict</code>，body 是 <code className="rounded bg-muted px-1">{'{"model":"名字","files":[{"name":"a.cor","b64":"..."}]}'}</code>。服务器之间对接用这个。</>,
          <>离线 / 本地：<code className="rounded bg-muted px-1">python scripts/predict_with_model.py --model models/x.joblib --data 新样品文件夹</code>，会把结果写成 CSV。</>,
        ]} />
      </Panel>
    </div>
  )
}
