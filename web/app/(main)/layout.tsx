'use client'

import { FolderProvider } from '@/lib/folder-context'
import { ControlBar } from '@/components/ControlBar'
import { DockNav } from '@/components/DockNav'

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <FolderProvider>
      <div className="flex min-h-screen flex-col">
        <div className="flex flex-1 flex-col px-4 pt-6 pb-8 sm:px-6 md:px-8 lg:px-12">
          <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 pb-24 md:gap-6">
            <ControlBar />
            {children}
          </div>
        </div>
      </div>
      <DockNav />
    </FolderProvider>
  )
}
