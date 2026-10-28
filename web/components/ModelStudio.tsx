'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteModel, listModels, modelDownloadUrl, predictSamples, trainModel, trainStatus } from '@/lib/api'
import type { PredictResult, PredictRow, SavedModel, TrainResult } from '@/lib/types'
import { Badge, Card, CardBody, HowTo, Note, SectionTitle, Table, Td } from '@/components/ui'

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

export default function ModelStudio({ folder, order, refFrac }: { folder: string; order: number; refFrac: number }) {
  const [models, setModels] = useState<SavedModel[]>([])
  const [loading, setLoading] = useState(true)
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
    try {
      const r = await listModels()
      setModels(r.models || [])
      setSel((cur) => cur || (r.models && r.models[0] ? r.models[0].name : ''))
    } catch {
      setModels([])
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
    <div className="space-y-4">
      <Card>
        <CardBody className="space-y-3">
          <SectionTitle sub="把当前文件夹的模型真的存成一个文件 · 约 20 秒（9 个算法 × 2 套输入）">
            训练并下载模型
          </SectionTitle>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={fmt}
              onChange={(e) => setFmt(e.target.value === 'pkl' ? 'pkl' : 'joblib')}
              disabled={training}
              className="h-9 rounded-lg border border-[#e8eaee] bg-white px-3 text-[12.5px] text-[#101828] outline-none"
            >
              <option value="joblib">.joblib（推荐，numpy 数组单独存，文件更小）</option>
              <option value="pkl">.pkl（纯 pickle，任何 Python 都能 pickle.load）</option>
            </select>
            <button
              onClick={onTrain}
              disabled={training || !folder}
              className="h-9 rounded-lg bg-[#101828] px-4 text-[12.5px] font-medium text-white disabled:opacity-50"
            >
              {training ? '正在训练… ' + waited + ' s' : '训练并下载模型'}
            </button>
            <span className="text-[12px] text-[#98a2b3]">
              训练用的是「数据」页里填的浓度；没有浓度梯度时会直接告诉你缺什么，不会存一个假模型。
            </span>
          </div>

          {trainErr ? (
            <Note tone="warn" title="这个文件夹现在还训练不出模型">{trainErr}</Note>
          ) : null}

          {trainRes ? (
            <div className="rounded-xl border border-[#e8eaee] bg-[#f9fafb] p-3">
              <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
                <Badge tone="ok">已保存</Badge>
                <span className="font-medium text-[#101828]">{trainRes.name}.{fmt}</span>
                <span className="text-[#667085]">
                  {trainRes.model.model} · {trainRes.model.input === 'curves' ? '整条曲线' : '手工特征'} ·
                  R² {(trainRes.model.r2 ?? 0).toFixed(3)} · RPD {(trainRes.model.rpd ?? 0).toFixed(2)} ·
                  {(trainRes.model.size_kb ?? 0).toFixed(1)} KB
                </span>
                <a
                  href={modelDownloadUrl(trainRes.name)}
                  className="rounded-lg border border-[#e8eaee] bg-white px-3 py-1 text-[12px] font-medium text-[#175cd3]"
                >
                  下载 {trainRes.name}.{fmt}
                </a>
                <a
                  href={modelDownloadUrl(trainRes.name)}
                  download
                  className="text-[12px] text-[#98a2b3] underline"
                >
                  再点一次直接存盘
                </a>
              </div>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[11.5px] leading-relaxed text-[#475467]">
                {trainRes.log.join('\n')}
              </pre>
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <SectionTitle sub={loading ? '正在读取…' : models.length + ' 个模型 · 存在服务器的 models/ 目录'}>
            模型仓库
          </SectionTitle>
          {models.length === 0 ? (
            <div className="py-6 text-center text-[12.5px] text-[#98a2b3]">
              还没有训练过模型。点上面的「训练并下载模型」，或者换到有浓度梯度的文件夹（演示数据）再试。
            </div>
          ) : (
            <Table head={['模型文件', '算法', '输入', 'R²', 'RPD', '大小', '操作']}>
              {models.map((m) => (
                <tr key={m.name} className={m.name === sel ? 'bg-[#f9fafb]' : undefined}>
                  <Td className="font-medium">{m.name}<span className="ml-1 text-[11px] text-[#98a2b3]">.{m.format}</span></Td>
                  <Td className="text-[#667085]">{m.model || '—'}</Td>
                  <Td className="text-[#667085]">{m.input === 'curves' ? '整条曲线' : m.input === 'features' ? '手工特征' : '—'}</Td>
                  <Td>{m.r2 !== undefined && m.r2 !== null ? m.r2.toFixed(3) : '—'}</Td>
                  <Td>{m.rpd !== undefined && m.rpd !== null ? m.rpd.toFixed(2) : '—'}</Td>
                  <Td className="text-[#667085]">{(m.size_kb ?? 0).toFixed(1)} KB</Td>
                  <Td>
                    <div className="flex gap-2">
                      <a href={modelDownloadUrl(m.name)} className="text-[12px] font-medium text-[#175cd3]">下载</a>
                      <button onClick={() => onDelete(m.name)} className="text-[12px] text-[#b42318]">删除</button>
                    </div>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardBody className="space-y-3">
          <SectionTitle sub="选一个模型，把新测的 .cor 拖进来 —— 不用碰命令行">
            用模型预测新样品
          </SectionTitle>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={sel}
              onChange={(e) => setSel(e.target.value)}
              className="h-9 min-w-[220px] rounded-lg border border-[#e8eaee] bg-white px-3 text-[12.5px] text-[#101828] outline-none"
            >
              {models.map((m) => (
                <option key={m.name} value={m.name}>{m.name}</option>
              ))}
            </select>
            <input
              type="file"
              multiple
              accept=".cor,.txt"
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
              className="text-[12.5px] text-[#475467] file:mr-2 file:h-9 file:rounded-lg file:border file:border-[#e8eaee] file:bg-white file:px-3 file:text-[12px] file:text-[#101828]"
            />
            <button
              onClick={onPredict}
              disabled={busy || !sel || files.length === 0}
              className="h-9 rounded-lg bg-[#101828] px-4 text-[12.5px] font-medium text-white disabled:opacity-50"
            >
              {busy ? '正在算…' : '预测' + (files.length ? '（' + files.length + ' 个文件）' : '')}
            </button>
            {pred && pred.rows.length ? (
              <button
                onClick={() => saveCsv(pred.rows)}
                className="h-9 rounded-lg border border-[#e8eaee] bg-white px-3 text-[12px] font-medium text-[#175cd3]"
              >
                下载 CSV
              </button>
            ) : null}
          </div>

          {predErr ? <Note tone="warn" title="预测失败">{predErr}</Note> : null}

          {pred ? (
            <>
              <Table head={['文件', '判定', '预测浓度', '可能的范围', 'I_MB', 'I_ref', '比值']}>
                {pred.rows.map((r) => (
                  <tr key={r.file}>
                    <Td className="font-medium">{r.file}</Td>
                    <Td>
                      {r.detected === false ? <Badge tone="mute">未检出</Badge>
                        : r.detected === true ? <Badge tone="ok">检出</Badge>
                        : <Badge tone="info">—</Badge>}
                    </Td>
                    <Td className="font-semibold">{r.detected === false ? '—' : fmtConc(r.pred_M)}</Td>
                    <Td className="text-[#667085]">
                      {r.detected === false ? '—' : fmtConc(r.lo_M) + ' – ' + fmtConc(r.hi_M)}
                    </Td>
                    <Td className="text-[#667085]">{r.I_MB !== undefined && r.I_MB !== null ? r.I_MB.toFixed(2) : '—'}</Td>
                    <Td className="text-[#667085]">{r.I_ref !== undefined && r.I_ref !== null ? r.I_ref.toFixed(2) : '—'}</Td>
                    <Td className="text-[#667085]">{r.ratio !== undefined && r.ratio !== null ? r.ratio.toFixed(3) : '—'}</Td>
                  </tr>
                ))}
              </Table>
              {pred.bad.length ? (
                <Note tone="warn" title={pred.bad.length + ' 个文件没算出来'}>
                  {pred.bad.map((b) => b.file + '：' + b.error).join('；')}
                </Note>
              ) : null}
              <div className="text-[12px] leading-relaxed text-[#98a2b3]">
                「未检出」是用模型卡里存的空白分布（3 SD）判的，不是回归算出来的 —— 回归只见过有浓度的样品，
                它没法自己说「这里什么都没有」。范围是 ±1 个交叉验证误差（约 {(pred.model.factor ?? 1).toFixed(1)} 倍）。
              </div>
            </>
          ) : null}

          <HowTo title="模型到底怎么「调用」" items={[
            <>这一页就是调用：选模型 → 上传 .cor → 出浓度。<b>不需要命令行</b>。上传的文件只在内存里算，不落盘。</>,
            <>自动化 / 批量：<code className="rounded bg-[#f2f4f7] px-1">POST /api/predict</code>，body 是 <code className="rounded bg-[#f2f4f7] px-1">{'{"model":"名字","files":[{"name":"a.cor","b64":"..."}]}'}</code>。服务器之间对接用这个。</>,
            <>离线 / 本地：<code className="rounded bg-[#f2f4f7] px-1">python scripts/predict_with_model.py --model models/x.joblib --data 新样品文件夹</code>，会把结果写成 CSV。</>,
          ]} />
        </CardBody>
      </Card>
    </div>
  )
}
