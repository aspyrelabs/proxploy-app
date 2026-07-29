import { EmptyState } from '../components/EmptyState'

export function PlaceholderPage({ title, phase, note }:
  { title: string; phase: string; note: string }) {
  return (
    <div>
      <h1 className="mb-5 font-display text-[22px] font-semibold">{title}</h1>
      <EmptyState title={`${title} lands in ${phase}`} note={note} />
    </div>
  )
}
