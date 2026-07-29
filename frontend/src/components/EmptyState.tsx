export function EmptyState({ title, note }: { title: string; note: string }) {
  return (
    <div className="grid place-items-center rounded-card border border-dashed border-line py-20 text-center">
      <div>
        <h2 className="font-display text-[16px] text-text-2">{title}</h2>
        <p className="mt-1 max-w-md text-[12.5px] text-text-3">{note}</p>
      </div>
    </div>
  )
}
