import type { Metadata } from 'next'
import { Inter, Noto_Sans_SC } from 'next/font/google'
import { ThemeProvider } from '@/components/common/layout/ThemeProvider'
import { Toaster } from '@/components/ui/sonner'
import './globals.css'

const inter = Inter({ variable: '--font-inter', subsets: ['latin'], display: 'swap' })

const notoSansSC = Noto_Sans_SC({
  variable: '--font-noto-sans-sc',
  subsets: ['latin'],
  display: 'swap',
  weight: ['300', '400', '500', '600', '700'],
})

export const metadata: Metadata = {
  title: '链霉素 DPV 检测平台',
  description: '差分脉冲伏安 · 定性筛查与定量',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="zh-CN"
      className={`${inter.variable} ${notoSansSC.variable} hide-scrollbar font-sans`}
      suppressHydrationWarning
    >
      <body className={`${inter.variable} ${notoSansSC.variable} hide-scrollbar font-sans antialiased`}>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem disableTransitionOnChange>
          {children}
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  )
}
