export type Meta = {
  folder: string
  n_curves: number
  n_electrodes: number
  n_groups: number
  n_qc: number
  n_points: number
  window: [number, number]
  metric: string
  metric_cn: string
  metric_available: string[]
  qc_threshold: number | null
  qc_median: number | null
  technique?: string
  technique_cn?: string
  technique_counts?: Record<string, number>
  technique_options?: string[]
}

export type GroupRow = {
  name: string
  n: number
  n_elec: number
  mean: number | null
  sd: number | null
  cv_pct: number | null
  color: string | null
  n_qc?: number
  mean_qc?: number | null
  sd_qc?: number | null
}

export type SampleRow = {
  file: string
  group: string
  electrode: string
  value: number | null
  I_MB: number | null
  I_ref: number | null
  qc_pass: boolean
  batch?: string
  label?: number | null
  concentration_M?: number | null
  role?: string
}

export type Series = {
  name: string
  mean: number[]
  sd: number[] | null
  n: number
  color: string | null
}

export type RawTrace = { file: string; group: string; y: number[] }

export type Fit = {
  error?: string
  a?: number
  b?: number
  r2?: number
  syx?: number
  direction?: string
  LOD_M?: number | null
  LOQ_M?: number | null
  LOD_error?: string
  quality?: string
  n_std?: number
  levels_M?: number[]
}

export type BatchFitRow = {
  batch: string
  n?: number
  levels?: number
  a?: number
  b?: number
  r2?: number
  syx?: number
  LOD_M?: number | null
  LOQ_M?: number | null
  note?: string
}

export type FitBatch = {
  model?: string
  r2?: number
  pooled_r2?: number
  rmse_log_lobo?: number
  direction?: string
  error?: string
  LOD_M?: number | null
  LOQ_M?: number | null
  batches?: BatchFitRow[]
}

export type Screening = {
  error?: string
  neg_group: string
  pos_group: string
  metric: string
  neg_mean: number
  neg_sd: number
  pos_mean: number
  pos_sd: number
  n_neg_elec: number
  n_pos_elec: number
  n_neg_scan: number
  n_pos_scan: number
  ratio: number
  effect_d: number
  p: number
  p_floor: number
  k: number
  sign: number
  cutoff: number
  direction: string
  false_pos: number
  missed: number
  separates: boolean
  gap: number
  accuracy: number
}

export type Verdict = {
  file: string
  group: string
  electrode: string
  value: number
  batch?: string
  verdict: 'positive' | 'negative' | 'unknown'
  text: string
  detail?: string
  C: number | null
  C_lo: number | null
  C_hi: number | null
  C_text: string | null
}

export type StatRow = { feature: string; label: string; F: number; p: number; eta2: number; n: number }
export type TukeyRow = { A: string; B: string; diff: number; p: number; lo: number; hi: number }
export type PcaPoint = { file: string; group: string; pc1: number; pc2: number; pc3: number }
export type ModelInfo = {
  error?: string
  accuracy?: number
  balanced_accuracy?: number
  class_support?: Record<string, number>
  elec_per_class?: Record<string, number>
  min_elec_per_class?: number
  n_scans?: number
  n_folds?: number
  labels?: string[]
  confusion?: number[][]
  chance?: number
  perm?: {
    observed: number
    observed_accuracy?: number
    null_mean: number
    null_p95: number
    p_value: number
    null: number[]
  }
}
export type CalibPoint = { file: string; group: string; conc_M: number; logc: number; value: number }
export type ImportanceRow = { feature: string; label: string; v: number }

export type Analysis = {
  meta: Meta
  errors: { file: string; error: string }[]
  groups: GroupRow[]
  samples: SampleRow[]
  curves: { grid: number[]; series: Series[]; raw?: RawTrace[] }
  fit: Fit
  fit_batch?: FitBatch | null
  screening?: Screening | null
  verdicts: Verdict[]
  stats?: { anova: StatRow[]; tukey: TukeyRow[]; summary: any[]; error?: string }
  pca?: { var: number[]; points: PcaPoint[]; error?: string }
  model?: ModelInfo
  importance?: ImportanceRow[]
  calib_points?: CalibPoint[]
}

export type RegModelRow = {
  set: string
  name: string
  r2: number
  rmse: number
  mae: number
  rpd: number
  n: number
  n_folds: number
  scale: string
  rmse_dex?: number
  factor?: number
  rel_err_pct?: number
}

export type Regression = {
  error?: string
  n_standards?: number
  n_levels?: number
  n_electrodes?: number
  n_batches?: number
  mode?: string
  unit?: string
  n_units?: number
  decades?: number
  scale?: string
  models?: RegModelRow[]
  best?: string
  best_set?: string
  best_row?: RegModelRow
  best_pred?: { true: number[]; pred: number[] }
  learning?: { model?: string; scale?: string; points?: { n_train: number; rmse: number; sd: number }[]; error?: string }
  importance?: { model?: string; rows?: { feature: string; v: number; sd: number }[]; error?: string }
  meta?: { folder: string; n_points: number; metric: string; n_curves: number }
}

export type PaperRow = { item: string; ours: string; ref: string }

export type PaperTable = {
  error?: string
  folder?: string
  metric?: string
  area_cm2?: number | null
  rows?: PaperRow[]
  note?: string
  markdown?: string
  counts?: { n_standards?: number; n_blanks?: number; n_levels?: number; n_electrodes?: number; n_curves?: number }
}

export type Electrode = {
  model?: string
  area_cm2?: number
  method?: string
  measured?: string
  detail?: any
}

export type AreaFit = {
  error?: string
  area_cm2?: number
  slope_uA_per_sqrt_V_s?: number
  intercept_uA?: number
  r2?: number
  r2_vs_v?: number
  n_points?: number
  resid?: { v_mV_s: number; ip_uA: number; pred_uA: number }[]
  warnings?: string[]
}
