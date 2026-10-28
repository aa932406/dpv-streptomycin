'use client'

import { useEffect, useMemo, useState } from 'react'
import { Save, Sparkles } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { saveMetadata, type MetaRow } from '@/lib/api'
import { Badge, Card, HowTo, Loading, Note, SectionTitle, StatCard } from '@/components/ui'

const INPUT =
  'w-full rounded-md border border-[#e8eaee] bg-white px-2 py-1 text-[12.5px] text-[#101828] ' +
  'outline-none transition focus:border-[#2e90fa] focus:ring-2 focus:ring-[#2e90fa]/15'

const SELECT =
  'rounded-md border border-[#e8eaee] bg-white px-2 py-1 text-[12px] text-[#344054] outline-none ' +
  'transition focus:border-[#2e90fa] focus:ring-2 focus:ring-[#2e90fa]/15'

const BTN =
  'inline-flex items-center gap-1 rounded-md border border-[#e8eaee] bg-white px-2.5 py-1.5 ' +
  'text-[12px] font-medium text-[#344054] transition hover:bg-[#f9fafb] disabled:opacity-40'

const BTN_DARK =
  'inline-flex items-center gap-1 rounded-md bg-[#101828] px-2.5 py-1.5 text-[12px] ' +
  'font-medium text-white transition hover:bg-[#1d2939] disabled:opacity-40'

type ColKey = keyof MetaRow

const COLS: { key: ColKey | 'qc'; label: string; hint: string; desc: string; eg: string; edit: boolean }[] = [
  {
    key: 'file',
    label: '文件',
    hint: '一次扫描一个',
    desc: '仪器导出的 .cor 文件。一行 = 一次扫描，文件名不可改，它就是这个样品的身份。',
    eg: '材料10uM.MB-dpv2.cor',
    edit: false,
  },
  {
    key: 'group',
    label: '分组',
    hint: '同一条件同名',
    desc: '实验条件。条件完全相同的曲线填同一个名字，不同条件填不同名字。统计和对比都按这一列分组。',
    eg: 'material+MB / target+Enz',
    edit: true,
  },
  {
    key: 'electrode',
    label: '电极',
    hint: '同一支电极同名',
    desc: '电极编号。默认取文件名，所以看着像文件名。同一支电极重复扫描（_ReStart、-dpv2）必须填同一个名字，否则「留一电极」交叉验证会把同一次测量当成两次独立重复，准确率虚高。',
    eg: 'E3（同组内唯一）',
    edit: true,
  },
  {
    key: 'concentration_M',
    label: '浓度 (M)',
    hint: '留空 / 0 / >0',
    desc: '链霉素浓度，单位 mol/L。三种填法决定这个样品在分析里算什么：留空 = 未知样品（工具要判定它）、0 = 空白、> 0 = 标准点（用来拟合曲线）。',
    eg: '1e-6（= 1 µM）',
    edit: true,
  },
  {
    key: 'batch',
    label: '批次',
    hint: '哪天做的',
    desc: '测量批次。不同日期、不同批 MOF 必须填不同的值。批次之间信号会整体漂移，多批次时按批标定靠这一列。',
    eg: '20261010',
    edit: true,
  },
  {
    key: 'label',
    label: '标签',
    hint: '1=有 0=没有',
    desc: '真值：这个样品里到底有没有链霉素。1 = 有，0 = 没有，留空 = 不知道或不需要。只给分类模型（LDA / 随机森林）和定性筛查用；不做分类就不必填。',
    eg: '1（加标了）/ 0（空白基质）',
    edit: true,
  },
  {
    key: 'role',
    label: '角色',
    hint: '一般不用填',
    desc: '这条曲线在校准里的身份，通常由浓度列自动推断：留空→未知样品、0→空白、>0→标准点。只有需要覆盖推断时才手填（blank / standard / sample / material）。',
    eg: '留空（自动）',
    edit: true,
  },
  {
    key: 'qc',
    label: 'QC',
    hint: '自动判定',
    desc: '内参峰（+0.35 V）电流是否够强。太弱的曲线电极没洗干净或修饰失败，会被剔除，不参与统计与建模。',
    eg: '通过 / 剔除',
    edit: false,
  },
]

const UNITS: { k: string; label: string; mul: number }[] = [
  { k: '1', label: '不换算（原样）', mul: 1 },
  { k: 'pM', label: 'pM → M', mul: 1e-12 },
  { k: 'nM', label: 'nM → M', mul: 1e-9 },
  { k: 'uM', label: 'µM → M', mul: 1e-6 },
  { k: 'mM', label: 'mM → M', mul: 1e-3 },
]


export default function DataPage() {
  const { data, loading, error, folder, reload } = useFolder()
  const [rows, setRows] = useState<MetaRow[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const [sel, setSel] = useState<Set<number>>(new Set())
  const [bulkCol, setBulkCol] = useState<ColKey>('concentration_M')
  const [bulkVal, setBulkVal] = useState('')
  const [flash, setFlash] = useState<string | null>(null)

  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [regexOpen, setRegexOpen] = useState(false)
  const [regexPat, setRegexPat] = useState('(\\d+(?:\\.\\d+)?)\\s*nM')
  const [regexUnit, setRegexUnit] = useState('nM')

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
    setSel(new Set())
    setSaved(null)
    setErr(null)
    setFlash(null)
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
    const groups = new Set(rows.map((r) => r.group).filter(Boolean))
    return { blank, std, unknown, batches: batches.size, groups: groups.size }
  }, [rows])

  const dupPairs = useMemo(() => {
    const base = (s: string) =>
      s.replace(/(?:_ReStart)+$/i, '').replace(/[-_ ]?(?:dpv|DPV)[-_ ]?\d*$/i, '').replace(/[-_ ]?\d+$/i, '')
    const seen = new Map<string, string[]>()
    for (const r of rows) {
      const e = (r.electrode || '').trim()
      if (!e) continue
      const k = r.group + '||' + base(e)
      const cur = seen.get(k) || []
      if (!cur.includes(e)) cur.push(e)
      seen.set(k, cur)
    }
    const out: { group: string; names: string[] }[] = []
    for (const [k, names] of seen) {
      if (names.length > 1) out.push({ group: k.split('||')[0], names })
    }
    return out
  }, [rows])

  if (loading) return <Loading />
  if (error) return <Note tone="bad" title="后端没有响应">{error}</Note>
  if (!data) return null

  const set = (i: number, k: ColKey, v: string) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)))

  const targets = () => (sel.size ? Array.from(sel).sort((a, b) => a - b) : rows.map((_, i) => i))

  function toggle(i: number) {
    setSel((s) => {
      const n = new Set(s)
      if (n.has(i)) n.delete(i)
      else n.add(i)
      return n
    })
  }

  function applyBulk() {
    const idx = targets()
    const v = bulkVal.trim()
    if (bulkCol === 'concentration_M' && v !== '' && !isFinite(Number(v))) {
      setFlash('浓度必须是数字（如 1e-6）或留空，' + v + ' 不是数字，没有修改。')
      return
    }
    setRows((rs) => rs.map((r, i) => (idx.includes(i) ? { ...r, [bulkCol]: v } : r)))
    setFlash('已把 ' + idx.length + ' 行的「' + labelOf(bulkCol) + '」改成「' + (v || '（空）') + '」，记得点右上角保存。')
  }

  function applyPaste() {
    const lines = pasteText.split(/\r?\n/).map((s) => s.trim()).filter((s) => s !== '')
    const idx = targets()
    const n = Math.min(lines.length, idx.length)
    if (!n) { setFlash('粘贴的内容是空的，没有修改。'); return }
    setRows((rs) =>
      rs.map((r, i) => {
        const at = idx.indexOf(i)
        return at >= 0 && at < n ? { ...r, [bulkCol]: lines[at] } : r
      }),
    )
    setFlash('已填入 ' + n + ' 行，记得保存。')
  }

  function applyRegex() {
    let re: RegExp
    try {
      re = new RegExp(regexPat)
    } catch (e) {
      setFlash('正则写错了：' + String(e))
      return
    }
    const mul = UNITS.find((u) => u.k === regexUnit)?.mul ?? 1
    const idx = targets()
    let hit = 0
    const preview: string[] = []
    setRows((rs) =>
      rs.map((r, i) => {
        if (!idx.includes(i)) return r
        const m = r.file.match(re)
        if (!m || m[1] == null) return r
        const raw = m[1].trim()
        const num = Number(raw)
        const val = isFinite(num) ? String(num * mul) : raw
        hit += 1
        if (preview.length < 3) preview.push(r.file + ' → ' + val)
        return { ...r, [bulkCol]: val }
      }),
    )
    setFlash(
      hit
        ? '从文件名提取了 ' + hit + ' 行到「' + labelOf(bulkCol) + '」，例：' + preview.join('；') + '，记得保存。'
        : '没有文件名匹配这条正则。',
    )
  }

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

  const groupNames = Array.from(new Set(rows.map((r) => r.group).filter(Boolean)))


  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight text-[#101828]">数据</h1>
          <p className="mt-1 text-[12.5px] text-[#667085]">
            这张表就是你的实验记录。填好之后保存，所有页面立刻用新值 · 文件来自 data/{folder}/
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
      {flash ? <Note tone="info">{flash}</Note> : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="标准点" value={stats.std} sub="浓度 > 0，用来拟合曲线" />
        <StatCard label="空白" value={stats.blank} sub="浓度填 0，算 LOD 要 3 条以上" />
        <StatCard label="未知样品" value={stats.unknown} sub="浓度留空，工具来判定" />
        <StatCard label="批次 / 分组" value={stats.batches + ' / ' + stats.groups} sub="不同日期要分开填" />
      </div>

      <Card className="px-5 py-4">
        <SectionTitle sub="点开看每一列到底填什么">这 8 列分别是什么意思</SectionTitle>
        <div className="mt-1 grid gap-x-8 md:grid-cols-2">
          {COLS.map((c) => (
            <div key={String(c.key)} className="flex gap-3 border-t border-[#f2f4f7] py-2.5">
              <div className="w-[62px] shrink-0 text-[12.5px] font-medium text-[#101828]">{c.label}</div>
              <div className="min-w-0">
                <div className="text-[12.5px] leading-relaxed text-[#475467]">{c.desc}</div>
                <div className="mt-0.5 text-[11.5px] text-[#98a2b3]">例：{c.eg}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>


      <Card className="px-5 py-4">
        <SectionTitle sub="一行 = 一次扫描；改完点右上角保存">数据表</SectionTitle>

        <div className="mt-2 space-y-2 rounded-xl border border-[#eef0f3] bg-[#fbfcfd] px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-[#667085]">
              已选 <b className="text-[#101828] tnum">{sel.size || '0'}</b> / {rows.length} 行
            </span>
            <select
              className={SELECT}
              value=""
              onChange={(e) => {
                const g = e.target.value
                if (!g) return
                const idx = rows.map((r, i) => (r.group === g ? i : -1)).filter((i) => i >= 0)
                setSel(new Set(idx))
                setFlash('已选中「' + g + '」组 ' + idx.length + ' 行，下面填值点「应用到已选」。')
                e.target.value = ''
              }}
            >
              <option value="">按分组全选…</option>
              {groupNames.map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
            <span className="text-[12px] text-[#98a2b3]">|</span>
            <select className={SELECT} value={String(bulkCol)} onChange={(e) => setBulkCol(e.target.value as ColKey)}>
              {COLS.filter((c) => c.edit).map((c) => (
                <option key={String(c.key)} value={String(c.key)}>{c.label}</option>
              ))}
            </select>
            <input
              className={INPUT + ' !w-[150px]'}
              placeholder="改成什么（留空=清空）"
              value={bulkVal}
              onChange={(e) => setBulkVal(e.target.value)}
            />
            <button className={BTN_DARK} onClick={applyBulk}>
              应用到{sel.size ? '已选' : '全部'}
            </button>
            {sel.size ? (
              <button className={BTN} onClick={() => setSel(new Set())}>清空选择</button>
            ) : null}
          </div>


          <div className="flex flex-wrap items-center gap-2">
            <button className={BTN} onClick={() => { setRegexOpen((v) => !v); setPasteOpen(false) }}>
              <Sparkles size={12} /> 从文件名提取
            </button>
            <button className={BTN} onClick={() => { setPasteOpen((v) => !v); setRegexOpen(false) }}>
              粘贴整列
            </button>
            <span className="text-[11.5px] text-[#98a2b3]">
              两种批量方式都只改上面选的那一列、以及已选的行（没选就是全部行）
            </span>
          </div>

          {regexOpen ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-[#eef0f3] pt-2">
              <span className="text-[12px] text-[#667085]">文件名正则（第 1 个括号就是要的值）</span>
              <input className={INPUT + ' !w-[260px] font-mono'} value={regexPat} onChange={(e) => setRegexPat(e.target.value)} />
              <select className={SELECT} value={regexUnit} onChange={(e) => setRegexUnit(e.target.value)}>
                {UNITS.map((u) => (
                  <option key={u.k} value={u.k}>{u.label}</option>
                ))}
              </select>
              <button className={BTN_DARK} onClick={applyRegex}>提取并填入</button>
            </div>
          ) : null}

          {pasteOpen ? (
            <div className="border-t border-[#eef0f3] pt-2">
              <div className="mb-1 text-[12px] text-[#667085]">
                从 Excel 复制一列粘进来，按行序填到上面选的那一列（每行一个值，空行忽略）
              </div>
              <textarea
                className={INPUT + ' h-[88px] font-mono'}
                placeholder="每行一个值"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
              <button className={BTN_DARK + ' mt-1.5'} onClick={applyPaste}>填入</button>
            </div>
          ) : null}
        </div>


        {dupPairs.length ? (
          <div className="mt-2">
            <Note tone="warn" title="有电极看起来是同一支">
              {dupPairs.map((d, i) => (
                <div key={i}>
                  「{d.group}」组里 {d.names.join(' 和 ')} 去掉末尾编号后同名。如果它们其实是同一支电极，请把「电极」列改成同一个名字再保存；确实是两支不同电极就不用管。
                </div>
              ))}
            </Note>
          </div>
        ) : null}

        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[1120px] border-collapse text-[12.5px]">
            <thead>
              <tr className="text-left text-[11.5px] text-[#667085]">
                <th className="w-[28px] pb-2 pr-1 align-bottom font-medium">
                  <input
                    type="checkbox"
                    checked={sel.size === rows.length && rows.length > 0}
                    onChange={(e) => setSel(e.target.checked ? new Set(rows.map((_, i) => i)) : new Set())}
                  />
                </th>
                {COLS.map((c) => (
                  <th key={String(c.key)} className="pb-2 pr-3 align-bottom font-medium" title={c.desc}>
                    <div className="whitespace-nowrap text-[#344054]">{c.label}</div>
                    <div className="mt-0.5 whitespace-nowrap text-[10.5px] font-normal leading-tight text-[#98a2b3]">{c.hint}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const s = String(r.concentration_M).trim()
                const v = s === '' ? null : Number(s)
                const tag = v == null || !isFinite(v) ? 'unknown' : v === 0 ? 'blank' : v > 0 ? 'std' : 'unknown'
                const picked = sel.has(i)
                return (
                  <tr key={r.file} className={'border-t border-[#f2f4f7]' + (picked ? ' bg-[#f5f9ff]' : '')}>
                    <td className="py-1.5 pr-1">
                      <input type="checkbox" checked={picked} onChange={() => toggle(i)} />
                    </td>
                    <td className="max-w-[190px] truncate py-1.5 pr-3 text-[#475467]" title={r.file}>{r.file}</td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT} value={r.group} onChange={(e) => set(i, 'group', e.target.value)} />
                    </td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT} value={r.electrode} onChange={(e) => set(i, 'electrode', e.target.value)} />
                    </td>
                    <td className="py-1.5 pr-3">
                      <div className="flex w-[196px] items-center gap-1.5">
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
                      <input className={INPUT + ' !w-[104px]'} value={r.batch} onChange={(e) => set(i, 'batch', e.target.value)} />
                    </td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT + ' !w-[54px]'} placeholder="0/1" value={r.label} onChange={(e) => set(i, 'label', e.target.value)} />
                    </td>
                    <td className="py-1.5 pr-3">
                      <input className={INPUT + ' !w-[92px]'} placeholder="自动" value={r.role} onChange={(e) => set(i, 'role', e.target.value)} />
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


        <HowTo
          title="浓度那列到底填什么（三种填法）"
          items={[
            <>
              <b>留空</b> = 未知样品。工具会在「结论」页告诉你有没有检出、浓度是多少、95% 区间多宽。
            </>,
            <>
              <b>填 0</b> = 空白。没有加链霉素的样品，用来算 LOD（检测限）。至少要 3 条，否则算不出 LOD。
            </>,
            <>
              <b>填大于 0</b> = 标准点。已知浓度的加标样品，用来拟合浓度到信号的曲线。至少要 3 个不同浓度、总共 4 条以上。
            </>,
            <>
              单位是 mol/L：1 pM = 1e-12、1 nM = 1e-9、1 µM = 1e-6、1 mM = 1e-3。
            </>,
            <>
              不用一行一行填：上面「按分组全选」加「应用到已选」，或者「从文件名提取」「粘贴整列」，三种都能批量。
            </>,
          ]}
        />
      </Card>
    </div>
  )
}

function labelOf(k: ColKey): string {
  return COLS.find((c) => c.key === k)?.label || String(k)
}
