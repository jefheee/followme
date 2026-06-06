import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'GitHub Async Growth Bot',
  description: 'Clean & Monochrome High Contrast Dashboard',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
