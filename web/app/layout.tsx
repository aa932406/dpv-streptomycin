import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: '链霉素 DPV 检测平台',
  description: '差分脉冲伏安 · 定性筛查与定量',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  )
}
