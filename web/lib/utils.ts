import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 1.23e-9 M -> "1.23 nM"; keeps three significant digits. */
export function fmtConc(m: number | null | undefined): string {
  if (m == null || !isFinite(m)) return '—'
  if (m === 0) return '0'
  const a = Math.abs(m)
  const units: [number, string][] = [[1, 'M'], [1e-3, 'mM'], [1e-6, 'µM'], [1e-9, 'nM'], [1e-12, 'pM']]
  for (const [s, u] of units) {
    if (a >= s) return trim3(m / s) + ' ' + u
  }
  return trim3(m / 1e-15) + ' fM'
}

function trim3(v: number): string {
  const a = Math.abs(v)
  if (a >= 100) return v.toFixed(0)
  if (a >= 10) return v.toFixed(1)
  if (a >= 1) return v.toFixed(2)
  return v.toPrecision(3)
}

export function fmtNum(v: number | null | undefined, nd = 2): string {
  if (v == null || !isFinite(v)) return '—'
  return v.toFixed(nd)
}

export function fmtP(p: number | null | undefined): string {
  if (p == null || !isFinite(p)) return '—'
  if (p <= 0) return '< 1e-16'
  if (p < 1e-4) return p.toExponential(1)
  return p.toFixed(3)
}

/** Long feature names wrap and blow up the stat card; keep the head only. */
export function shortLabel(s: string, max = 12): string {
  const cut = s.replace(/\s*\([^)]*\)\s*$/, '')
  return cut.length > max ? cut.slice(0, max - 1) + '…' : cut
}

/** Round axis ticks (0.2 steps) instead of 0.54 / 0.27. */
export function niceTicks(lo: number, hi: number, n = 7): number[] {
  const span = hi - lo
  if (!(span > 0)) return [lo]
  const raw = span / n
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const norm = raw / mag
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag
  const start = Math.ceil(lo / step) * step
  const out: number[] = []
  for (let v = start; v <= hi + step * 1e-6; v += step) out.push(+v.toFixed(6))
  return out
}

/** Chinese names for the feature columns the backend emits. */
export const FEATURE_CN: Record<string, string> = {
  I_MB: 'MB 峰电流',
  I_ref: '内参峰电流',
  ratio: 'MB/内参 比值',
  anodic_H: '阳极峰高',
  cathodic_H: '阴极峰高',
  anodic_Ep: '阳极峰位',
  cathodic_Ep: '阴极峰位',
  Q: '总电荷',
  ocp: '开路电位',
  I_start: '起始电流',
  I_mid: '中段电流',
  I_end: '末端电流',
}

export function featureCN(feature: string, fallback?: string): string {
  return FEATURE_CN[feature] || fallback || feature
}

/** Turn the backend's English calibration guard into something a user can act on. */
export function explainFitError(err: string | null | undefined): string {
  const e = String(err || '')
  if (!e) return ''
  if (/no row has a concentration/i.test(e))
    return '数据表里一个浓度值都没有填。先把每个样品的链霉素浓度填进去：空白填 0，标准点填已知浓度，未知样品留空。'
  if (/need at least 4 standards/i.test(e))
    return '已知浓度的标准点不到 4 条。至少 4 条标准点，建议每个浓度 3 支独立电极。'
  if (/need at least 3 different concentrations|calibration needs at least 3 distinct/i.test(e))
    return '这批数据只有一个浓度水平，画不出校准曲线。定量至少需要 3 个浓度梯度（例如 0 / 10 nM / 1 µM）。'
  if (/calibration is not usable/i.test(e))
    return '峰电流不随浓度单调变化，校准线没有可用斜率。先检查是不是空白波动太大，或者浓度梯度没有覆盖响应区间。'
  if (/no such folder|not enough data/i.test(e)) return e
  return e
}

export function pct(v: number | null | undefined, nd = 1): string {
  if (v == null || !isFinite(v)) return '—'
  return (v * 100).toFixed(nd) + '%'
}
