import type { Analysis, AreaFit, Electrode, PaperTable, Regression } from './types'

export type FolderInfo = { id: string; label: string; n_files: number; is_demo?: boolean }

async function j<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: 'no-store' })
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return (await r.json()) as T
}

export const getFolders = () => j<{ folders: FolderInfo[] }>('/api/folders')

export const getAnalysis = (folder: string, order = 4, refFrac = 0.35, technique = 'auto') =>
  j<Analysis>('/api/analyse?folder=' + encodeURIComponent(folder) +
    '&order=' + order + '&ref_frac=' + refFrac + '&technique=' + encodeURIComponent(technique))

export type MetaRow = {
  file: string
  group: string
  electrode: string
  concentration_M: string
  batch: string
  label: string
  role: string
}

export async function saveMetadata(folder: string, rows: MetaRow[]): Promise<{ ok: boolean; rows: number }> {
  const r = await fetch('/api/metadata', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder, rows }),
  })
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return (await r.json()) as { ok: boolean; rows: number }
}

export const reportUrl = (folder: string, order = 4, refFrac = 0.35, technique = 'auto') =>
  '/api/report?folder=' + encodeURIComponent(folder) + '&order=' + order +
  '&ref_frac=' + refFrac + '&technique=' + encodeURIComponent(technique)

export const getRegression = (folder: string, order = 4, refFrac = 0.35, technique = 'auto') =>
  j<Regression>('/api/regression?folder=' + encodeURIComponent(folder) +
    '&order=' + order + '&ref_frac=' + refFrac + '&technique=' + encodeURIComponent(technique))

export const getPaper = (folder: string, area = '') =>
  j<PaperTable>('/api/paper?folder=' + encodeURIComponent(folder) + '&area=' + encodeURIComponent(area))

export const getElectrode = () => j<Electrode>('/api/electrode')

export type CvFile = {
  file: string
  scan_rate_mV_s?: number
  ipa_uA?: number
  epa_v?: number
  ipc_uA?: number
  epc_v?: number
  dEp_mV?: number
  n_points?: number
  n_branches?: number
}

export const getCvFiles = (folder: string) =>
  j<{ folder: string; files: CvFile[] }>('/api/cvfiles?folder=' + encodeURIComponent(folder))

async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return (await r.json()) as T
}

export const fitArea = (body: {
  conc_mM: number
  n: number
  d_cm2_s: number
  points: { v_mV_s: number; ip_uA: number }[]
}) => post<AreaFit>('/api/area', body)

export const saveElectrode = (body: {
  area_cm2: number
  model: string
  method: string
  detail?: unknown
}) => post<{ ok: boolean; electrode: Electrode }>('/api/electrode', body)
