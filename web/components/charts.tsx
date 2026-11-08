'use client'

import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Area, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts'
import type { CalibPoint, ImportanceRow, PcaPoint, Series } from '@/lib/types'
import { featureCN, niceTicks } from '@/lib/utils'

const AXIS = { fontSize: 11, fill: '#475467' }
const GRID = '#eef0f3'
const CURVE_AXIS = '#111827'

function ticksFor(grid: number[], n = 6): number[] {
  if (!grid.length) return []
  return niceTicks(Math.min(...grid), Math.max(...grid), n)
}

function valueTicks(series: Series[], showBand: boolean): number[] {
  const values = series.flatMap((s) => s.mean.flatMap((v, i) => {
    if (!Number.isFinite(v)) return []
    if (showBand && s.sd && Number.isFinite(s.sd[i])) return [v - s.sd[i], v + s.sd[i]]
    return [v]
  }))
  if (!values.length) return []
  return niceTicks(Math.min(...values), Math.max(...values), 5)
}

function CurveTip({ active, payload, label }: any) {
  if (!active || !payload || !payload.length) return null
  const items = payload.filter((p: any) => !String(p.dataKey).includes('__'))
  if (!items.length) return null
  return (
    <div className="rounded-[10px] border border-[#e8eaee] bg-white px-2.5 py-2 text-[12px] shadow-[0_4px_12px_rgba(16,24,40,.08)]">
      <div className="mb-1 text-[11px] text-[#98a2b3]">E = {Number(label).toFixed(2)} V</div>
      {items.map((p: any) => (
        <div key={String(p.dataKey)} className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="h-[3px] w-3 shrink-0 rounded-full" style={{ background: p.color }} />
          <span className="text-[#475467]">{p.dataKey}</span>
          <span className="ml-auto pl-3 tabular-nums text-[#101828]">{Number(p.value).toFixed(2)} µA</span>
        </div>
      ))}
    </div>
  )
}

export function CurvesChart({
  grid, series, height = 320, showBand = false,
}: { grid: number[]; series: Series[]; height?: number; showBand?: boolean }) {
  const order = grid.map((_, i) => i).sort((a, b) => grid[a] - grid[b])
  const rows = order.map((i) => {
    const r: Record<string, number> = { x: grid[i] }
    series.forEach((s) => {
      r[s.name] = s.mean[i]
      if (showBand && s.sd) {
        // a Recharts band = an invisible area from 0..lo plus a stacked area of
        // height (hi-lo); drawing hi alone filled the whole way down to zero
        r[s.name + '__lo'] = s.mean[i] - s.sd[i]
        r[s.name + '__band'] = 2 * s.sd[i]
      }
    })
    return r
  })
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <ComposedChart data={rows} margin={{ top: 14, right: 24, bottom: 12, left: 18 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis
            dataKey="x" type="number" domain={['dataMin', 'dataMax']}
            ticks={ticksFor(grid)} tickFormatter={(v) => Number(v).toFixed(1)}
            tick={AXIS} axisLine={{ stroke: CURVE_AXIS, strokeWidth: 1.4 }}
            tickLine={{ stroke: CURVE_AXIS, strokeWidth: 1.2 }}
            label={{ value: 'Potential (V)', position: 'insideBottom', offset: -6, fontSize: 13, fontWeight: 600, fill: CURVE_AXIS }}
          />
          <YAxis
            domain={['auto', 'auto']} ticks={valueTicks(series, showBand)}
            tick={AXIS} axisLine={{ stroke: CURVE_AXIS, strokeWidth: 1.4 }}
            tickLine={{ stroke: CURVE_AXIS, strokeWidth: 1.2 }} width={54}
            tickFormatter={(v) => Number(v).toFixed(1)}
            label={{ value: 'Current (µA)', angle: -90, position: 'insideLeft', offset: 8, fontSize: 13, fontWeight: 600, fill: CURVE_AXIS }}
          />
          <Tooltip content={<CurveTip />} />
          {showBand
            ? series.map((s) =>
                s.sd ? (
                  <Area key={s.name + 'lo'} type="monotone" dataKey={s.name + '__lo'}
                    stackId={'b' + s.name} stroke="none" fill="transparent"
                    isAnimationActive={false} />
                ) : null,
              )
            : null}
          {showBand
            ? series.map((s) =>
                s.sd ? (
                  <Area key={s.name + 'band'} type="monotone" dataKey={s.name + '__band'}
                    stackId={'b' + s.name} stroke="none" fill={s.color || '#98a2b3'}
                    fillOpacity={0.13} isAnimationActive={false} />
                ) : null,
              )
            : null}
          {series.map((s) => (
            <Line key={s.name} type="monotone" dataKey={s.name} stroke={s.color || '#667085'}
              strokeWidth={1.8} dot={false} isAnimationActive={false} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Legend({ series }: { series: Series[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {series.map((s) => (
        <span key={s.name} className="flex items-center gap-1.5 text-[12px] text-[#475467]">
          <span className="h-[3px] w-4 rounded-full" style={{ background: s.color || '#98a2b3' }} />
          {s.name}
          <span className="text-[11px] text-[#98a2b3]">n={s.n}</span>
        </span>
      ))}
    </div>
  )
}

export function PcaScatter({ points, varPct, groupColors }: {
  points: PcaPoint[]
  varPct: number[]
  /** name -> hex, so a group keeps the same colour it has on the curve chart */
  groupColors?: Record<string, string>
}) {
  const groups = Array.from(new Set(points.map((p) => p.group)))
  const colors = ['#2e90fa', '#12b76a', '#f79009', '#f04438', '#7a5af8', '#0e9384', '#dc6803', '#667085']
  return (
    <div style={{ width: '100%', height: 330 }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 10, right: 16, bottom: 10, left: -8 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis type="number" dataKey="pc1" tick={AXIS} axisLine={false} tickLine={false}
            label={{ value: 'PC1 (' + ((varPct[0] || 0) * 100).toFixed(1) + '%)', position: 'insideBottom', offset: -4, fontSize: 11, fill: '#98a2b3' }} />
          <YAxis type="number" dataKey="pc2" tick={AXIS} axisLine={false} tickLine={false}
            label={{ value: 'PC2 (' + ((varPct[1] || 0) * 100).toFixed(1) + '%)', angle: -90, position: 'insideLeft', offset: 18, fontSize: 11, fill: '#98a2b3' }} />
          <ZAxis range={[55, 55]} />
          <Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e8eaee', fontSize: 12 }}
            formatter={(v: any, n: any) => [Number(v).toFixed(2), n === 'pc1' ? 'PC1' : 'PC2']} />
          {groups.map((g, i) => (
            <Scatter key={g} name={g} data={points.filter((p) => p.group === g)}
              fill={groupColors?.[g] || colors[i % colors.length]} fillOpacity={0.8} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ImportanceBars({ rows }: { rows: ImportanceRow[] }) {
  const data = rows.map((r) => ({ ...r, name: featureCN(r.feature, r.label) }))
  return (
    <div style={{ width: '100%', height: Math.max(240, data.length * 34) }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ ...AXIS, fontSize: 12 }} axisLine={false} tickLine={false} width={118} />
          <Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e8eaee', fontSize: 12 }}
            formatter={(v: any) => [Number(v).toFixed(3), '重要性']} />
          <Bar dataKey="v" fill="#2e90fa" radius={[0, 4, 4, 0]} barSize={14} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function CalibChart({ points, a, b }: { points: CalibPoint[]; a?: number; b?: number }) {
  const hasLine = a != null && b != null
  const xs = points.map((p) => p.logc)
  const lo = Math.min(...xs), hi = Math.max(...xs)
  const line = hasLine ? [{ logc: lo, value: a! + b! * lo }, { logc: hi, value: a! + b! * hi }] : []
  const byGroup = Array.from(new Set(points.map((p) => p.group)))
  const colors = ['#2e90fa', '#12b76a', '#f79009', '#f04438', '#7a5af8', '#0e9384']
  return (
    <div style={{ width: '100%', height: 300 }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 10, right: 16, bottom: 8, left: -8 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis type="number" dataKey="logc" domain={[lo - 0.25, hi + 0.25]} tick={AXIS}
            ticks={niceTicks(lo - 0.25, hi + 0.25, 5)} axisLine={false} tickLine={false}
            label={{ value: 'log10 C (M)', position: 'insideBottom', offset: -4, fontSize: 11, fill: '#98a2b3' }} />
          <YAxis type="number" dataKey="value" tick={AXIS} axisLine={false} tickLine={false}
            label={{ value: 'response', angle: -90, position: 'insideLeft', offset: 18, fontSize: 11, fill: '#98a2b3' }} />
          <ZAxis range={[60, 60]} />
          <Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e8eaee', fontSize: 12 }} />
          {byGroup.map((g, i) => (
            <Scatter key={g} name={g} data={points.filter((p) => p.group === g)}
              fill={colors[i % colors.length]} fillOpacity={0.85} />
          ))}
          {hasLine ? (
            <Scatter name="拟合" data={line} line={{ stroke: '#101828', strokeWidth: 1.5 }}
              shape={() => <g />} legendType="none" />
          ) : null}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

export function PermHist({ nulls, observed, p95 }: { nulls: number[]; observed: number; p95: number }) {
  if (!nulls.length) return null
  const bins = 18
  const lo = Math.min(...nulls, observed), hi = Math.max(...nulls, observed)
  const w = (hi - lo) / bins || 1
  const counts = new Array(bins).fill(0)
  nulls.forEach((v) => {
    const k = Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / w)))
    counts[k]++
  })
  const rows = counts.map((c, i) => ({ x: +(lo + w * (i + 0.5)).toFixed(3), n: c }))
  return (
    <div style={{ width: '100%', height: 240 }}>
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 22, right: 16, bottom: 4, left: -12 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="x" type="number" domain={[+(lo - w / 2).toFixed(3), +(hi + w / 2).toFixed(3)]}
            ticks={rows.filter((_, i) => i % 3 === 0).map((r) => r.x)} tick={AXIS}
            axisLine={false} tickLine={false} allowDataOverflow
            tickFormatter={(v) => (Number(v) * 100).toFixed(0) + '%'} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={34} />
          <Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e8eaee', fontSize: 12 }} />
          <ReferenceLine x={+observed.toFixed(3)} stroke="#b42318" strokeWidth={1.5}
            label={{ value: '实测 ' + (observed * 100).toFixed(0) + '%', position: 'insideTopRight', fontSize: 11, fill: '#b42318' }} />
          <ReferenceLine x={+p95.toFixed(3)} stroke="#98a2b3" strokeDasharray="4 3" />
          <Bar dataKey="n" fill="#b2ddff" radius={[3, 3, 0, 0]} barSize={9} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Long free-form Chinese group names overlap on a categorical axis, so the
 *  bars carry a short label and the full name stays in the tooltip. */
function shortGroup(s: string, max = 10) {
  const t = s.replace(/dpv-?\d*$/i, '').trim()
  return t.length > max ? t.slice(0, max) + '…' : t
}

export function GroupBars({ rows }: { rows: { name: string; mean: number; sd: number; color: string | null }[] }) {
  const maxLen = rows.length <= 5 ? 18 : 10   // few bars -> there is room for the full name
  const data = rows.map((r) => ({
    name: shortGroup(r.name, maxLen), full: r.name, mean: r.mean, sd: r.sd,
    color: r.color || '#2e90fa',
  }))
  return (
    <div style={{ width: '100%', height: 300 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={AXIS} axisLine={false} tickLine={false} interval={0}
            angle={-28} textAnchor="end" height={62} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44} />
          <Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e8eaee', fontSize: 12 }}
            labelFormatter={(v: any, p: any) => (p && p[0] ? p[0].payload.full : v)}
            formatter={(v: any) => [Number(v).toFixed(3), '均值']} />
          <Bar dataKey="mean" radius={[4, 4, 0, 0]} barSize={38}>
            {data.map((d, i) => <Cell key={i} fill={d.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}


/* ---------------------------------------------------------------- parity */
export function ParityChart({
  truth, pred, height = 340,
}: { truth: number[]; pred: number[]; height?: number }) {
  const pts = truth.map((t, i) => ({
    lx: Math.log10(Math.max(t, 1e-16)),
    ly: Math.log10(Math.max(pred[i], 1e-16)),
    c: t,
  }))
  if (!pts.length) return null
  const all = pts.flatMap((p) => [p.lx, p.ly])
  const lo = Math.floor(Math.min(...all))
  const hi = Math.ceil(Math.max(...all))
  const fmt = (v: number) => {
    const m = Math.pow(10, Number(v))
    if (m >= 1e-3 && m < 1) return (m * 1e6).toFixed(0) + ' µM'
    if (m >= 1e-6) return (m * 1e9).toFixed(0) + ' nM'
    if (m >= 1e-9) return (m * 1e12).toFixed(0) + ' pM'
    return m.toExponential(0) + ' M'
  }
  // axis ticks stay in one unit (exponent of 10) so the log axis reads cleanly
  const tick = (v: number) => '1e' + Math.round(Number(v))
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 12, right: 18, bottom: 14, left: 2 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis type="number" dataKey="lx" domain={[lo, hi]} tick={AXIS} axisLine={false}
            tickLine={false} tickFormatter={tick} tickCount={6}
            label={{ value: '真实浓度 (M)', position: 'insideBottom', offset: -6, fontSize: 11, fill: '#98a2b3' }} />
          <YAxis type="number" dataKey="ly" domain={[lo, hi]} tick={AXIS} axisLine={false}
            tickLine={false} tickFormatter={tick} tickCount={6} width={58}
            label={{ value: '预测浓度 (M)', angle: -90, position: 'insideLeft', offset: 4, fontSize: 11, fill: '#98a2b3' }} />
          <ReferenceLine
            segment={[{ x: lo, y: lo }, { x: hi, y: hi }]}
            stroke="#98a2b3" strokeDasharray="4 4" ifOverflow="extendDomain"
          />
          <Tooltip
            contentStyle={{ borderRadius: 10, border: '1px solid #e8eaee', fontSize: 12 }}
            formatter={(v: any, n: any) => [fmt(v), n === 'lx' ? '真实' : '预测']}
            labelFormatter={() => ''}
          />
          <Scatter data={pts} fill="#2e90fa" fillOpacity={0.75} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ---------------------------------------------------------- learning curve */
export function LearnCurve({
  points, height = 260,
}: { points: { n_train: number; rmse: number; sd: number }[]; height?: number }) {
  if (!points.length) return null
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <LineChart data={points} margin={{ top: 10, right: 16, bottom: 8, left: -10 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="n_train" tick={AXIS} axisLine={false} tickLine={false}
            label={{ value: '训练用电极数', position: 'insideBottom', offset: -4, fontSize: 11, fill: '#98a2b3' }} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={58}
            tickFormatter={(v) => Number(v).toFixed(1)}
            label={{ value: '留出误差 (dex)', angle: -90, position: 'insideLeft', offset: 2, fontSize: 11, fill: '#98a2b3' }} />
          <Tooltip
            contentStyle={{ borderRadius: 10, border: '1px solid #e8eaee', fontSize: 12 }}
            formatter={(v: any) => [Number(v).toFixed(2) + ' dex', '误差']}
            labelFormatter={(v) => '训练 ' + v + ' 支电极'}
          />
          <Line type="monotone" dataKey="rmse" stroke="#7a5af8" strokeWidth={2}
            dot={{ r: 3 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}


/* --------------------------------------------------------------- ratio */
/** I_MB against I_ref, one dot per curve.
 *
 *  The assay is ratiometric: MB is the signal, the MIL-101(Fe) Fe(III)/Fe(II)
 *  peak at +0.35 V is the internal reference. A curve whose signal really
 *  belongs to the target sits at a different slope through the origin, not
 *  merely higher up -- an electrode with a large area lifts both currents and
 *  slides the dot along the same diagonal. That is the whole point of plotting
 *  them against each other instead of as two separate bars.
 */
export function RatioScatter({ points, height = 330 }: {
  points: { file: string; group: string; I_MB: number; I_ref: number; color: string }[]
  height?: number
}) {
  const ok = points.filter((p) => p.I_MB > 0 && p.I_ref > 0)
  if (ok.length < 2) return null
  const groups = Array.from(new Set(ok.map((p) => p.group)))
  const all = ok.flatMap((p) => [p.I_MB, p.I_ref])
  const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...all))))
  const hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...all))))
  const ratios = [0.25, 0.5, 1, 2, 4]
  // log axes otherwise invent ticks like 3.317; keep 1-2-5 decades only
  const ticks: number[] = []
  for (let e = Math.log10(lo); e <= Math.log10(hi) + 1e-9; e++) {
    for (const m of [1, 2, 5]) {
      const v = m * Math.pow(10, e)
      if (v >= lo * 0.999 && v <= hi * 1.001) ticks.push(v)
    }
  }
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 12, right: 18, bottom: 16, left: -4 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis type="number" dataKey="I_ref" scale="log" domain={[lo, hi]} allowDataOverflow
            tick={AXIS} axisLine={false} tickLine={false} ticks={ticks} tickFormatter={(v) => String(v)}
            label={{ value: '内参峰电流 I_ref (µA)', position: 'insideBottom', offset: -8, fontSize: 11, fill: '#98a2b3' }} />
          <YAxis type="number" dataKey="I_MB" scale="log" domain={[lo, hi]} allowDataOverflow
            tick={AXIS} axisLine={false} tickLine={false} ticks={ticks} tickFormatter={(v) => String(v)} width={54}
            label={{ value: 'MB 峰电流 I_MB (µA)', angle: -90, position: 'insideLeft', offset: 14, fontSize: 11, fill: '#98a2b3' }} />
          {ratios.map((r) => (
            <ReferenceLine key={r} segment={[{ x: lo, y: lo * r }, { x: hi, y: hi * r }]}
              stroke={r === 1 ? '#98a2b3' : '#e4e7ec'} strokeDasharray={r === 1 ? '0' : '4 4'}
              label={r === 1 ? { value: 'I_MB = I_ref', position: 'insideTopLeft', fontSize: 10, fill: '#98a2b3' } : undefined} />
          ))}
          <ZAxis range={[60, 60]} />
          <Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e8eaee', fontSize: 12 }}
            formatter={(v: any, n: any) => [Number(v).toFixed(2) + ' µA', n === 'I_MB' ? 'MB 峰' : '内参峰']}
            labelFormatter={() => ''} />
          {groups.map((g) => (
            <Scatter key={g} name={g} data={ok.filter((p) => p.group === g)}
              fill={ok.find((p) => p.group === g)?.color || '#2e90fa'} fillOpacity={0.85} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}
