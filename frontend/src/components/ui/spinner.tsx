import { Loader2Icon } from 'lucide-react'

import { cn } from '@/lib/utils'

/**
 * The one "something is happening" animation, so a working control looks the
 * same wherever it is.
 *
 * `currentColor` and `size-4` by default, which makes it drop into a Button or
 * a StatusPill without either having to say anything about it: it inherits the
 * ink and the line-height of whatever it sits in.
 *
 * aria-hidden, always. It animates a fact the surrounding text already states
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
