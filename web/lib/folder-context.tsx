'use client'

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { getAnalysis, getFolders, type FolderInfo } from './api'
import type { Analysis } from './types'

type Ctx = {
  folders: FolderInfo[]
  folder: string
  setFolder: (f: string) => void
  data: Analysis | null
  loading: boolean
  error: string | null
  order: number
  refFrac: number
  technique: string
  setParams: (p: { order?: number; refFrac?: number; technique?: string }) => void
  reload: () => void
  refreshFolders: () => Promise<FolderInfo[]>
}

const C = createContext<Ctx | null>(null)

export function FolderProvider({ children }: { children: React.ReactNode }) {
  const [folders, setFolders] = useState<FolderInfo[]>([])
  const [folder, setFolder] = useState('')
  const [data, setData] = useState<Analysis | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [order, setOrder] = useState(4)
  const [refFrac, setRefFrac] = useState(0.35)
  const [technique, setTechnique] = useState('auto')
  const [tick, setTick] = useState(0)

  // restore the last folder / params so switching pages does not jump back to the default
  useEffect(() => {
    try {
      const f = localStorage.getItem('dpv.folder')
      const o = localStorage.getItem('dpv.order')
      const rf = localStorage.getItem('dpv.refFrac')
      const tq = localStorage.getItem('dpv.technique')
      if (f) setFolder(f)
      if (o) setOrder(Number(o))
      if (rf) setRefFrac(Number(rf))
      if (tq) setTechnique(tq)
    } catch { /* private mode */ }
  }, [])

  const refreshFolders = useCallback(async () => {
    const r = await getFolders()
    const list = r.folders || []
    setFolders(list)
    return list
  }, [])

  useEffect(() => {
    refreshFolders().then((list) => {
      const ids = new Set(list.map((f) => f.id))
      // Prefer a dated folder over an imported external dataset on first load.
      const real = list.filter((f) => !f.is_demo)
      const dated = real.filter((f) => /^\d{8}$/.test(f.id))
      const pool = dated.length ? dated : real
      const fallback = pool.length ? pool[pool.length - 1].id : list[0]?.id || ''
      setFolder((cur) => (cur && ids.has(cur) ? cur : fallback))
      if (!fallback) {
        setData(null)
        setError(null)
        setLoading(false)
      }
    }).catch((e) => { setError(String(e)); setLoading(false) })
  }, [refreshFolders])

  useEffect(() => {
    try {
      if (folder) localStorage.setItem('dpv.folder', folder)
      localStorage.setItem('dpv.order', String(order))
      localStorage.setItem('dpv.refFrac', String(refFrac))
      localStorage.setItem('dpv.technique', technique)
    } catch { /* ignore */ }
  }, [folder, order, refFrac, technique])

  useEffect(() => {
    if (!folder) return
    let alive = true
    setLoading(true)
    setError(null)
    getAnalysis(folder, order, refFrac, technique)
      .then((d) => {
        if (!alive) return
        setData(d)
        setLoading(false)
        // a technique picked in one folder may not exist in the next one
        const opts = d.meta?.technique_options || []
        if (technique !== 'auto' && technique !== 'all' && opts.length && !opts.includes(technique)) {
          setTechnique('auto')
        }
      })
      .catch((e) => { if (alive) { setError(String(e)); setLoading(false) } })
    return () => { alive = false }
  }, [folder, order, refFrac, technique, tick])

  const setParams = useCallback((p: { order?: number; refFrac?: number; technique?: string }) => {
    if (p.order != null) setOrder(p.order)
    if (p.refFrac != null) setRefFrac(p.refFrac)
    if (p.technique != null) setTechnique(p.technique)
  }, [])

  const reload = useCallback(() => setTick((t) => t + 1), [])

  return (
    <C.Provider value={{ folders, folder, setFolder, data, loading, error, order, refFrac, technique, setParams, reload, refreshFolders }}>
      {children}
    </C.Provider>
  )
}

export function useFolder() {
  const v = useContext(C)
  if (!v) throw new Error('useFolder must be used inside FolderProvider')
  return v
}
