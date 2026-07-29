export const CPU_GRADIENT = 'linear-gradient(90deg,#F5B544,#E0862B)'
export const RAM_GRADIENT = 'linear-gradient(90deg,#34D3C6,#5B9DF9)'
export const STORAGE_GRADIENT = 'linear-gradient(90deg,#A78BFA,#6D5AE6)'
export const DANGER_GRADIENT = 'linear-gradient(90deg,#F26D6D,#c93b3b)'

export function UsageBar({ pct, gradient = CPU_GRADIENT }: {
  pct: number | null | undefined
  gradient?: string
}) {
  const w = Math.min(100, Math.max(0, pct ?? 0))
  return (
    <div className="h-1.5 overflow-hidden rounded-full" style={{ background: '#1d2733' }}>
      <div
        className="h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none"
        style={{ width: `${w}%`, background: gradient }}
      />
    </div>
  )
}
