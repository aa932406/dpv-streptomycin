'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { AlertTriangle, Check, FileUp, FlaskConical, FolderUp, Layers, Save, Sparkles, SquarePen, X } from 'lucide-react'
import { useFolder } from '@/lib/folder-context'
import { saveMetadata, uploadFolder, type MetaRow } from '@/lib/api'
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
import { StatCard } from '@/components/common/layout/StatCard'
import { HowTo } from '@/components/HowTo'
import { Panel } from '@/components/Panel'
import { NoCurves, PageError, PageLoading } from '@/components/PageState'

type ColKey = keyof MetaRow

const COLS: { key: ColKey | 'qc'; label: string; hint: string; desc: string; eg: string; edit: boolean }[] = [
  {
    key: 'file', label: '文件', hint: '一次扫描一个', edit: false,
    desc: '仪器导出的 .cor 文件。一行 = 一次扫描，文件名不可改，它就是这个样品的身份。',
    eg: '材料10uM.MB-dpv2.cor',
  },
  {
    key: 'group', label: '分组', hint: '同一条件同名', edit: true,
    desc: '实验条件。条件完全相同的曲线填同一个名字，不同条件填不同名字。统计和对比都按这一列分组。',
    eg: 'material+MB / target+Enz',
  },
  {
    key: 'electrode', label: '电极', hint: '同一支电极同名', edit: true,
    desc: '电极编号。默认取文件名，所以看着像文件名。同一支电极重复扫描（_ReStart、-dpv2）必须填同一个名字，否则「留一电极」交叉验证会把同一次测量当成两次独立重复，准确率虚高。',
    eg: 'E3（同组内唯一）',
  },
  {
    key: 'concentration_M', label: '浓度 (M)', hint: '留空 / 0 / >0', edit: true,
    desc: '链霉素浓度，单位 mol/L。三种填法决定这个样品在分析里算什么：留空 = 未知样品（工具要判定它）、0 = 空白、> 0 = 标准点（用来拟合曲线）。',
    eg: '1e-6（= 1 µM）',
  },
  {
    key: 'batch', label: '批次', hint: '哪天做的', edit: true,
    desc: '测量批次。不同日期、不同批 MOF 必须填不同的值。批次之间信号会整体漂移，多批次时按批标定靠这一列。',
    eg: '20261010',
  },
  {
    key: 'label', label: '标签', hint: '1=有 0=没有', edit: true,
    desc: '真值：这个样品里到底有没有链霉素。1 = 有，0 = 没有，留空 = 不知道或不需要。只给分类模型（LDA / 随机森林）和定性筛查用；不做分类就不必填。',
    eg: '1（加标了）/ 0（空白基质）',
  },
  {
    key: 'role', label: '角色', hint: '一般不用填', edit: true,
    desc: '这条曲线在校准里的身份，通常由浓度列自动推断：留空→未知样品、0→空白、>0→标准点。只有需要覆盖推断时才手填（blank / standard / sample / material）。',
    eg: '留空（自动）',
  },
  {
    key: 'qc', label: 'QC', hint: '自动判定', edit: false,
    desc: '内参峰（+0.35 V）电流是否够强。太弱的曲线电极没洗干净或修饰失败，会被剔除，不参与统计与建模。',
    eg: '通过 / 剔除',
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
  const { data, loading, error, folder, folders, setFolder, refreshFolders, reload } = useFolder()
  const [rows, setRows] = useState<MetaRow[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const [sel, setSel] = useState<Set<number>>(new Set())
  const [bulkCol, setBulkCol] = useState<ColKey>('concentration_M')
  const [bulkVal, setBulkVal] = useState('')
  const [flash, setFlash] = useState<string | null>(null)
  const [uploadFiles, setUploadFiles] = useState<File[]>([])
  const [uploadName, setUploadName] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadErr, setUploadErr] = useState<string | null>(null)
  const [uploadDone, setUploadDone] = useState<string | null>(null)
  const directoryInput = useRef<HTMLInputElement>(null)

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

  const uploadBytes = uploadFiles.reduce((sum, file) => sum + file.size, 0)
  const uploadable = uploadFiles.some((file) => file.name.toLowerCase().endsWith('.cor')) &&
    /^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$/.test(uploadName.trim()) &&
    !folders.some((item) => item.id.toLowerCase() === uploadName.trim().toLowerCase())

  function onDirectoryChange(event: React.ChangeEvent<HTMLInputElement>) {
    const chosen = Array.from(event.target.files || [])
    const corFiles = chosen.filter((file) => file.name.toLowerCase().endsWith('.cor'))
    const metadata = chosen.filter((file) => file.name.toLowerCase() === 'metadata.csv')
    setUploadFiles([...corFiles, ...metadata.slice(0, 1)])
    setUploadErr(null)
    setUploadDone(null)
    const firstPath = chosen[0] as (File & { webkitRelativePath?: string }) | undefined
    const pathFolder = firstPath?.webkitRelativePath?.split('/')[0] || ''
    if (pathFolder) setUploadName(pathFolder.replace(/[^A-Za-z0-9._ -]/g, '_').slice(0, 80))
  }

  async function onUpload() {
    if (!uploadable) return
    setUploading(true)
    setUploadErr(null)
    setUploadDone(null)
    try {
      const name = uploadName.trim()
      const result = await uploadFolder(name, uploadFiles)
      await refreshFolders()
      setFolder(result.folder)
      reload()
      setUploadDone('已导入 ' + result.files + ' 个 .cor 文件到 data/' + result.folder +
        (result.has_metadata ? '，并导入 metadata.csv。' : '。'))
      setUploadFiles([])
      if (directoryInput.current) directoryInput.current.value = ''
    } catch (e) {
      let message = String((e as Error)?.message ?? e)
      try { message = JSON.parse(message).detail || message } catch { /* keep raw response */ }
      setUploadErr(message)
    } finally {
      setUploading(false)
    }
  }

  if (loading && !data) return <PageLoading />
  if (error && !data) return <PageError title="后端没有响应" detail={error} />

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
  const allPicked = sel.size === rows.length && rows.length > 0

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <Panel title="导入实验目录" sub="选择本地目录，导入其中的 .cor 曲线和可选 metadata.csv">
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={directoryInput}
            type="file"
            multiple
            accept=".cor,.csv"
            // @ts-expect-error webkitdirectory is supported by Chromium-based browsers
            webkitdirectory=""
            onChange={onDirectoryChange}
            className="sr-only"
          />
          <Button variant="outline" size="sm" onClick={() => directoryInput.current?.click()} disabled={uploading}>
            <FolderUp className="size-3.5" /> 选择本地目录
          </Button>
          <Input
            className="h-8 w-[220px] text-xs"
            aria-label="导入后的目录名称"
            placeholder="导入后的目录名称"
            value={uploadName}
            onChange={(event) => setUploadName(event.target.value)}
            disabled={uploading}
          />
          <Button size="sm" onClick={onUpload} disabled={!uploadable || uploading}>
            <FileUp className="size-3.5" /> {uploading ? '正在上传…' : '上传并导入'}
          </Button>
        </div>
        <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
          {uploadFiles.length
            ? uploadFiles.filter((file) => file.name.toLowerCase().endsWith('.cor')).length + ' 个 .cor 文件 · ' +
              (uploadFiles.some((file) => file.name.toLowerCase() === 'metadata.csv') ? '含 metadata.csv · ' : '') +
              (uploadBytes / 1024 / 1024).toFixed(1) + ' MB · 同名目录不会覆盖'
            : '仅上传所选目录内的 .cor 文件和根目录 metadata.csv；单文件最多 25 MB，总计最多 200 MB。'}
        </p>
        {uploadErr ? <p role="alert" className="mt-2 break-words text-[11px] text-red-600">导入失败：{uploadErr}</p> : null}
        {uploadDone ? <p role="status" className="mt-2 text-[11px] text-emerald-700 dark:text-emerald-300">{uploadDone}</p> : null}
      </Panel>

      {!data || !data.meta?.n_curves ? (
        <NoCurves />
      ) : <>
      <PageHeader
        title="数据"
        description={'这张表就是你的实验记录。填好之后保存，所有页面立刻用新值 · 文件来自 data/' + folder + '/'}
        actions={
          <>
            <Button variant="outline" size="sm" className="rounded-full" asChild>
              <Link href="/calib">看校准</Link>
            </Button>
            <Button size="sm" className="rounded-full" onClick={onSave} disabled={saving}>
              <Save className="size-3.5" />
              {saving ? '保存中…' : '保存并重新分析'}
            </Button>
          </>
        }
      />

      {saved ? (
        <div className="flex items-start gap-2.5 rounded-[20px] bg-emerald-500/10 px-4 py-3 ring-1 ring-emerald-500/20">
          <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" />
          <div className="text-[11px] leading-5">{saved}</div>
        </div>
      ) : null}
      {err ? (
        <div className="flex items-start gap-2.5 rounded-[20px] bg-red-500/10 px-4 py-3 ring-1 ring-red-500/20">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-red-600" />
          <div className="min-w-0 text-[11px] leading-5"><b>保存失败：</b>{err}</div>
        </div>
      ) : null}
      {flash ? (
        <div className="rounded-[20px] bg-blue-500/10 px-4 py-3 ring-1 ring-blue-500/20">
          <div className="text-[11px] leading-5 text-blue-700 dark:text-blue-300">{flash}</div>
        </div>
      ) : null}

      <section className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
        <StatCard label="标准点" value={stats.std} hint="浓度 > 0，用来拟合曲线" icon={FlaskConical} tone="info" />
        <StatCard label="空白" value={stats.blank} hint="浓度填 0，算 LOD 要 3 条以上" icon={SquarePen} delay={0.04} />
        <StatCard label="未知样品" value={stats.unknown} hint="浓度留空，工具来判定" icon={Layers} tone="warning" delay={0.08} />
        <StatCard label="批次 / 分组" value={stats.batches + ' / ' + stats.groups} hint="不同日期要分开填" icon={X} delay={0.12} />
      </section>

      <Panel title="这 8 列分别是什么意思" sub="点开看每一列到底填什么">
        <div className="grid gap-x-8 md:grid-cols-2">
          {COLS.map((c) => (
            <div key={String(c.key)} className="flex gap-3 border-t border-border/50 py-2.5 first:border-t-0 md:[&:nth-child(2)]:border-t-0">
              <div className="w-[62px] shrink-0 text-xs font-medium">{c.label}</div>
              <div className="min-w-0">
                <div className="text-[11px] leading-5 text-muted-foreground">{c.desc}</div>
                <div className="mt-0.5 text-[10px] text-muted-foreground/70">例：{c.eg}</div>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="数据表" sub="一行 = 一次扫描；改完点右上角保存">
        <div className="space-y-2 rounded-2xl bg-background/60 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-muted-foreground">
              已选 <b className="tabular-nums text-foreground">{sel.size || '0'}</b> / {rows.length} 行
            </span>
            <Select
              value=""
              onValueChange={(g) => {
                if (!g) return
                const idx = rows.map((r, i) => (r.group === g ? i : -1)).filter((i) => i >= 0)
                setSel(new Set(idx))
                setFlash('已选中「' + g + '」组 ' + idx.length + ' 行，下面填值点「应用到已选」。')
              }}
            >
              <SelectTrigger size="sm" className="w-[150px]"><SelectValue placeholder="按分组全选…" /></SelectTrigger>
              <SelectContent>
                {groupNames.map((g) => <SelectItem key={g} value={g}>{g}</SelectItem>)}
              </SelectContent>
            </Select>
            <span className="text-[11px] text-muted-foreground/50">|</span>
            <Select value={String(bulkCol)} onValueChange={(v) => setBulkCol(v as ColKey)}>
              <SelectTrigger size="sm" className="w-[110px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                {COLS.filter((c) => c.edit).map((c) => (
                  <SelectItem key={String(c.key)} value={String(c.key)}>{c.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              className="h-8 w-[160px] text-xs"
              placeholder="改成什么（留空=清空）"
              value={bulkVal}
              onChange={(e) => setBulkVal(e.target.value)}
            />
            <Button size="sm" className="h-8 rounded-full px-3 text-[11px]" onClick={applyBulk}>
              应用到{sel.size ? '已选' : '全部'}
            </Button>
            {sel.size ? (
              <Button variant="outline" size="sm" className="h-8 rounded-full px-3 text-[11px]" onClick={() => setSel(new Set())}>
                清空选择
              </Button>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline" size="sm" className="h-8 rounded-full px-3 text-[11px]"
              onClick={() => { setRegexOpen((v) => !v); setPasteOpen(false) }}
            >
              <Sparkles className="size-3" /> 从文件名提取
            </Button>
            <Button
              variant="outline" size="sm" className="h-8 rounded-full px-3 text-[11px]"
              onClick={() => { setPasteOpen((v) => !v); setRegexOpen(false) }}
            >
              粘贴整列
            </Button>
            <span className="text-[10px] text-muted-foreground/70">
              两种批量方式都只改上面选的那一列、以及已选的行（没选就是全部行）
            </span>
          </div>

          {regexOpen ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-border/50 pt-2">
              <span className="text-[11px] text-muted-foreground">文件名正则（第 1 个括号就是要的值）</span>
              <Input className="h-8 w-[260px] font-mono text-xs" value={regexPat} onChange={(e) => setRegexPat(e.target.value)} />
              <Select value={regexUnit} onValueChange={setRegexUnit}>
                <SelectTrigger size="sm" className="w-[140px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {UNITS.map((u) => <SelectItem key={u.k} value={u.k}>{u.label}</SelectItem>)}
                </SelectContent>
              </Select>
              <Button size="sm" className="h-8 rounded-full px-3 text-[11px]" onClick={applyRegex}>提取并填入</Button>
            </div>
          ) : null}

          {pasteOpen ? (
            <div className="border-t border-border/50 pt-2">
              <div className="mb-1 text-[11px] text-muted-foreground">
                从 Excel 复制一列粘进来，按行序填到上面选的那一列（每行一个值，空行忽略）
              </div>
              <textarea
                className="h-[88px] w-full rounded-xl border border-transparent bg-muted/55 px-3 py-2 font-mono text-xs outline-none focus-visible:bg-muted/70 focus-visible:ring-2 focus-visible:ring-ring/15"
                placeholder="每行一个值"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
              <Button size="sm" className="mt-1.5 h-8 rounded-full px-3 text-[11px]" onClick={applyPaste}>填入</Button>
            </div>
          ) : null}
        </div>

        {dupPairs.length ? (
          <div className="mt-2 flex items-start gap-2.5 rounded-2xl bg-amber-500/10 px-3.5 py-2.5 ring-1 ring-amber-500/20">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
            <div className="min-w-0 space-y-1 text-[11px] leading-5">
              <div className="font-medium">有电极看起来是同一支</div>
              {dupPairs.map((d, i) => (
                <div key={i} className="text-muted-foreground">
                  「{d.group}」组里 {d.names.join(' 和 ')} 去掉末尾编号后同名。如果它们其实是同一支电极，请把「电极」列改成同一个名字再保存；确实是两支不同电极就不用管。
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="mt-3 overflow-hidden rounded-2xl bg-background/60">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">
                  <input
                    type="checkbox"
                    className="size-3.5 accent-foreground"
                    checked={allPicked}
                    onChange={(e) => setSel(e.target.checked ? new Set(rows.map((_, i) => i)) : new Set())}
                  />
                </TableHead>
                {COLS.map((c) => (
                  <TableHead key={String(c.key)} title={c.desc}>
                    <div className="whitespace-nowrap text-foreground">{c.label}</div>
                    <div className="mt-0.5 whitespace-nowrap text-[10px] font-normal leading-tight text-muted-foreground/70">{c.hint}</div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r, i) => {
                const s = String(r.concentration_M).trim()
                const v = s === '' ? null : Number(s)
                const tag = v == null || !isFinite(v) ? 'unknown' : v === 0 ? 'blank' : v > 0 ? 'std' : 'unknown'
                const picked = sel.has(i)
                return (
                  <TableRow key={r.file} className={picked ? 'bg-blue-500/[0.06]' : undefined}>
                    <TableCell>
                      <input type="checkbox" className="size-3.5 accent-foreground" checked={picked} onChange={() => toggle(i)} />
                    </TableCell>
                    <TableCell className="max-w-[190px] truncate text-muted-foreground" title={r.file}>{r.file}</TableCell>
                    <TableCell>
                      <Input className="h-8 w-[150px] text-xs" value={r.group} onChange={(e) => set(i, 'group', e.target.value)} />
                    </TableCell>
                    <TableCell>
                      <Input className="h-8 w-[150px] text-xs" value={r.electrode} onChange={(e) => set(i, 'electrode', e.target.value)} />
                    </TableCell>
                    <TableCell>
                      <div className="flex w-[196px] items-center gap-1.5">
                        <Input
                          className="h-8 text-xs"
                          placeholder="留空 = 未知"
                          value={r.concentration_M}
                          onChange={(e) => set(i, 'concentration_M', e.target.value)}
                        />
                        {tag === 'blank'
                          ? <Badge variant="secondary">空白</Badge>
                          : tag === 'std'
                            ? <Badge variant="outline" className="border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300">标准</Badge>
                            : <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">未知</Badge>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Input className="h-8 w-[104px] text-xs" value={r.batch} onChange={(e) => set(i, 'batch', e.target.value)} />
                    </TableCell>
                    <TableCell>
                      <Input className="h-8 w-[56px] text-xs" placeholder="0/1" value={r.label} onChange={(e) => set(i, 'label', e.target.value)} />
                    </TableCell>
                    <TableCell>
                      <Input className="h-8 w-[92px] text-xs" placeholder="自动" value={r.role} onChange={(e) => set(i, 'role', e.target.value)} />
                    </TableCell>
                    <TableCell>
                      {data.samples[i]?.qc_pass
                        ? <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">通过</Badge>
                        : <Badge variant="outline" className="border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300">剔除</Badge>}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>

        <HowTo
          title="浓度那列到底填什么（三种填法）"
          items={[
            <><b>留空</b> = 未知样品。工具会在「结论」页告诉你有没有检出、浓度是多少、95% 区间多宽。</>,
            <><b>填 0</b> = 空白。没有加链霉素的样品，用来算 LOD（检测限）。至少要 3 条，否则算不出 LOD。</>,
            <><b>填大于 0</b> = 标准点。已知浓度的加标样品，用来拟合浓度到信号的曲线。至少要 3 个不同浓度、总共 4 条以上。</>,
            <>单位是 mol/L：1 pM = 1e-12、1 nM = 1e-9、1 µM = 1e-6、1 mM = 1e-3。</>,
            <>不用一行一行填：上面「按分组全选」加「应用到已选」，或者「从文件名提取」「粘贴整列」，三种都能批量。</>,
          ]}
        />
      </Panel>
      </>}
    </div>
  )
}

function labelOf(k: ColKey): string {
  return COLS.find((c) => c.key === k)?.label || String(k)
}
