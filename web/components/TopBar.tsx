'use client'

import Link from 'next/link'
import { ChevronDown, Download, FlaskConical, SlidersHorizontal, FolderOpen } from 'lucide-react'
import { useState } from 'react'
import { useFolder } from '@/lib/folder-context'
import { reportUrl } from '@/lib/api'

export function TopBar() {
  const { folders, folder, setFolder, order, refFrac, technique, setParams, data } = useFolder()
  const [open, setOpen] = useState(false)
  const cur = folders.find((f) => f.id === folder)
  const TECH_CN: Record<string, string> = {
    DPV: '差分脉冲伏安 (DPV)',
    'DPV-stripping': '差分脉冲溶出伏安',
    SWV: '方波伏安 (SWV)',
    'SWV-stripping': '方波溶出伏安',
  }
  const techOpts = data?.meta?.technique_options || []

  return (
    <header className="sticky top-0 z-30 border-b border-[#e8eaee] bg-white/85 backdrop-blur">
      <div className="mx-auto flex h-[58px] max-w-7xl items-center gap-3 px-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#101828] text-white">
          <FlaskConical size={18} />
        </div>
        <div className="mr-auto leading-tight">
          <div className="text-[14.5px] font-semibold text-[#101828]">链霉素 DPV 检测平台</div>
          <div className="text-[11.5px] text-[#98a2b3]">差分脉冲伏安 · 定性筛查与定量</div>
        </div>

        <div className="flex items-center gap-1.5 rounded-lg border border-[#e4e7ec] bg-white px-2.5 py-1.5">
          <FolderOpen size={14} className="text-[#98a2b3]" />
          <select
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            className="max-w-[190px] cursor-pointer bg-transparent text-[12.5px] text-[#344054] outline-none"
          >
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}{f.is_demo ? '（演示）' : ''} · {f.n_files} 个文件
              </option>
            ))}
          </select>
          <ChevronDown size={13} className="text-[#98a2b3]" />
        </div>

        <div className="relative">
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-lg border border-[#e4e7ec] bg-white px-2.5 py-1.5 text-[12.5px] text-[#344054] hover:bg-[#f9fafb]"
          >
            <SlidersHorizontal size={14} className="text-[#98a2b3]" />
            分析参数
          </button>
          {open ? (
            <div className="absolute right-0 mt-2 w-72 rounded-xl border border-[#e8eaee] bg-white p-4 shadow-lg">
              <label className="block text-[12px] text-[#667085]">基线拟合阶数</label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="range" min={2} max={6} step={1} value={order}
                  onChange={(e) => setParams({ order: Number(e.target.value) })}
                  className="w-full accent-[#101828]"
                />
                <span className="w-4 text-[12.5px] font-medium tnum">{order}</span>
              </div>
              <label className="mt-3 block text-[12px] text-[#667085]">
                内参峰 QC 下限（本批中位数的比例）
              </label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="range" min={0} max={1} step={0.05} value={refFrac}
                  onChange={(e) => setParams({ refFrac: Number(e.target.value) })}
                  className="w-full accent-[#101828]"
                />
                <span className="w-9 text-[12.5px] font-medium tnum">{Math.round(refFrac * 100)}%</span>
              </div>
              <label className="mt-3 block text-[12px] text-[#667085]">扫描类型</label>
              <div className="mt-1 flex items-center gap-1.5 rounded-lg border border-[#e4e7ec] px-2 py-1.5">
                <select
                  value={technique}
                  onChange={(e) => setParams({ technique: e.target.value })}
                  className="w-full cursor-pointer bg-transparent text-[12.5px] text-[#344054] outline-none"
                >
                  <option value="auto">
                    自动{data?.meta?.technique_cn ? '（' + data.meta.technique_cn + '）' : ''}
                  </option>
                  {techOpts.map((t) => (
                    <option key={t} value={t}>{TECH_CN[t] || t}</option>
                  ))}
                  <option value="all">全部混在一起（仅看形状）</option>
                </select>
                <ChevronDown size={13} className="shrink-0 text-[#98a2b3]" />
              </div>
              <p className="mt-3 text-[11.5px] leading-relaxed text-[#98a2b3]">
                改参数会重新分析整个文件夹。内参门槛越低，保留的曲线越多，但噪声也越大。
                一个文件夹里混了 CV 或溶出伏安时，默认只分析占多数的那种脉冲扫描 ——
                不同扫描方式的峰电流不在一个量纲上。
              </p>
            </div>
          ) : null}
        </div>

        <a
          href={data ? reportUrl(folder, order, refFrac, technique) : '#'}
          className="flex items-center gap-1.5 rounded-lg bg-[#101828] px-3 py-1.5 text-[12.5px] font-medium text-white hover:bg-[#1d2939]"
        >
          <Download size={14} />
          导出报告
        </a>
      </div>
      {cur ? null : null}
    </header>
  )
}
