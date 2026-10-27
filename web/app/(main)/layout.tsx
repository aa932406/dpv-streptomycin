'use client'

import { FolderProvider } from '@/lib/folder-context'
import { TopBar } from '@/components/TopBar'
import { Dock } from '@/components/Dock'

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <FolderProvider>
      <div className="min-h-screen pb-40">
        <TopBar />
        <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
        <Dock />
      </div>
    </FolderProvider>
  )
}
