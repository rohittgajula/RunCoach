import { lazy, Suspense, useEffect, useState } from 'react'

// R17 §10: the form and the return-to-run preview are a lazy chunk.
const IllnessSheet = lazy(() => import('./IllnessSheet'))

export function IllnessLauncher({ mode, open, onClose }: { mode: 'start' | 'recover'; open: boolean; onClose: () => void }) {
  // Mounted on first open, then kept so the sheet can slide away.
  const [mounted, setMounted] = useState(open)
  useEffect(() => { if (open) setMounted(true) }, [open])
  if (!mounted) return null
  return (
    <Suspense fallback={null}>
      <IllnessSheet open={open} onClose={onClose} mode={mode} />
    </Suspense>
  )
}

