import { Loader2Icon } from 'lucide-react'

import { cn } from '@/lib/utils'

/**
 * The shared "something is happening" spinner.
 *
 * aria-hidden, always: it animates a fact the surrounding text already states
 * ("Working", "Stopping"), and a screen reader announcing a spinner adds
 * nothing to a label that already says what is going on. A caller with no such
 * text owes one.
 */
export function Spinner({ className, ...props }: React.ComponentProps<'svg'>) {
  return (
    <Loader2Icon
      role="presentation"
      aria-hidden
      data-slot="spinner"
      className={cn('size-4 animate-spin', className)}
      {...props}
    />
  )
}
