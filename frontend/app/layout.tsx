import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'SDRC BMD Report System',
  description: 'Bone Mineral Density — DEXA scan reports for SDRC Diagnostics, Secunderabad',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased font-sans">{children}</body>
    </html>
  )
}
