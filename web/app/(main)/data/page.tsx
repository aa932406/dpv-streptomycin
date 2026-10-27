'use client'

import { useEffect, useMemo, useState } from 'react'
import { Save } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { saveMetadata, type MetaRow } from '@/lib/api'
import { Badge, Card, Loading, Note, SectionTitle, StatCard } from '@/components/ui'

const INPUT =
  'w-full rounded-md border border-[#e8eaee] bg-white px-2 py-1 text-[12.5px] text-[#101828] ' +
  'outline-none transition focus:border-[#2e90fa] focus:ring-2 focus:ring-[#2e90fa]/15'

export default function DataPage() {
  const { data, loading, error, folder, reload } = useFolder()
  const [rows, setRows] = useState<MetaRow[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!data?.samples) return
    setRows(
      data.samples.map((s) => ({
        file: s.file,
        group: s.group || '',
        electrode: s.electrode || '',
        concentration_M: s.concentration_M == null ? '' : String(s.concentration_M),
        batch: s.batch || '',
        label: s.label == null ? '' : String(s.label),
        role: s.role || '',
      })),
    )
    setSaved(null)
    setErr(null)
  }, [data])

  const stats = useMemo(() => {
    let blank = 0
    let std = 0
    let unknown = 0
    for (const r of rows) {
      const s = String(r.concentration_M).trim()
      if (s === '') { unknown += 1; continue }
      const v = Number(s)
      if (!isFinite(v)) { unknown += 1; continue }
      if (v === 0) blank += 1
      else if (v > 0) std += 1
      else unknown += 1
    }
    const batches = new Set(rows.map((r) => r.batch).filter(Boolean))
    return { blank, std, unknown, batches: batches.size }
  }, [rows])

  if (loading) return <Loading />
  if (error) return <Note tone="bad" title="后端没有响应">{error}</Note>
  if (!data) return null

  const set = (i: number, k: keyof MetaRow, v: string) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)))

  async function onSave() {
    setSaving(true)
    setErr(null)
    setSaved(null)
    try {
      const r = await saveMetadata(folder, rows)
      setSaved('已保存 ' + r.rows + ' 行到 data/' + folder + '/metadata.csv，正在重新分析…')
      reload()
    } catch (e) {
      setErr(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight text-[#101828]">数据</h1>
          <p className="mt-1 text-[12.5px] text-[#667085]">
            浓度 / 批次 / 标签填在这里，保存后所有页面立刻用新值 · 文件来自 data/{folder}/
          </p>
        </div>
        <button
          onClick={onSave}
          disabled={saving}
          className="flex items-center gap-1.5 rounded-lg bg-[#101828] px-3.5 py-2 text-[12.5px] font-medium text-white transition hover:bg-[#1d2939] disabled:opacity-50"
        >
          <Save size={14} />
          {saving ? '保存中…' : '保存并重新分析'}
        </button>
      </div>

      {saved ? <Note tone="ok">{saved}</Note> : null}
      {err ? <Note tone="bad" title="保存失败">{err}</Note> : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="标准点" value={stats.std} sub="浓度 > 0" />
        <StatCard label="空白" value={stats.blank} sub="浓度填 0" />
        <StatCard label="未知样品" value={stats.unknown} sub="浓度留空" />
        <StatCard label="批次" value={stats.batches} sub="不同测量批次" />
      </div>

      <Card className="px-5 py-4">
        <SectionTitle sub="浓度单位是 mol/L：1 nM = 1e-9，1 µM = 1e-6，10 pM = 1e-11">浓度与分组</SectionTitle>
        <div className="mt-1 overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse text-[12.5px]">
            <thead>
              <tr className="text-left text-[11.5px] text-[#667085]">
                <th className="pb-2 pr-3 font-medium">文件</th>
                <th className="pb-2 pr-3 font-medium">分组</th>
                <th className="pb-2 pr-3 font-medium">电极</th>
                <th className="pb-2 pr-3 font-medium">浓度 (M)</th>
                <th className="pb-2 pr-3 font-medium">批次</th>
                <th className="pb-2 pr-3 font-medium">标签</th>
                <th className="pb-2 pr-3 font-medium">角色</th>
                <th className="pb-2 font-medium">QC</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const s = String(r.concentration_M).trim()
                const v = s === '' ? null : Number(s)
                const tag = v == null || !isFinite(v) ? 'unknown' : v === 0 ? 'blank' : v > 0 ? 'std' : 'unknown'
                return (
                  <tr key={r.file} className="border-t border-[#f2f4f7]">
                    <td className="max-w-[220px] truncate py-1.5 pr-3 text-[#475467]" title={r.file}>{r.file}</td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT} value={r.group} onChange={(e) => set(i, 'group', e.target.value)} />
                    </td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT} value={r.electrode} onChange={(e) => set(i, 'electrode', e.target.value)} />
                    </td>
                    <td className="py-1.5 pr-3">
                      <div className="flex w-[210px] items-center gap-1.5">
                        <input
                          className={INPUT}
                          placeholder="留空 = 未知"
                          value={r.concentration_M}
                          onChange={(e) => set(i, 'concentration_M', e.target.value)}
                        />
                        {tag === 'blank' ? <Badge tone="mute">空白</Badge>
                          : tag === 'std' ? <Badge tone="info">标准</Badge>
                            : <Badge tone="warn">未知</Badge>}
                      </div>
                    </td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT} value={r.batch} onChange={(e) => set(i, 'batch', e.target.value)} />
                    </td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT} placeholder="0/1" value={r.label} onChange={(e) => set(i, 'label', e.target.value)} />
                    </td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT} placeholder="blank/standard/sample" value={r.role} onChange={(e) => set(i, 'role', e.target.value)} />
                    </td>
                    <td className="py-1.5">
                      {data.samples[i]?.qc_pass ? <Badge tone="ok">通过</Badge> : <Badge tone="bad">剔除</Badge>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11.5px] leading-relaxed text-[#98a2b3]">
          浓度：<b>留空</b> = 未知样品（工具会给出浓度和 95% 区间）；<b>0</b> = 空白（算 LOD 用，至少 3 条）；
          <b> &gt; 0</b> = 标准点（至少 3 个不同浓度、共 4 条以上）。
          标签：1 = 有靶标，0 = 无靶标，用来做定性筛查。批次：不同日期 / 不同批 MOF 填不同的值，按批标定会用到。
        </p>
      </Card>
    </div>
  )
}
