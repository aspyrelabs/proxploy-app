import type { ComponentProps } from "react"
import { ChevronLeftIcon, ChevronRightIcon, MoreHorizontalIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

/**
 * shadcn/ui `pagination`, vendored and adapted in two places (the nav/ul/li
 * structure, data-slot attributes, and class lists are upstream's):
 *
 * 1. This project's hand-written ui/button.tsx predates shadcn: no `asChild`,
 *    and its variants are primary/ghost/danger/go with sizes md/icon-xs. The
 *    adaptation happens here (variant="ghost", size="sm") rather than
 *    overwriting Button, which every route renders through.
 *
 * 2. Upstream's controls are anchors (the registry demo uses href="#"); an
 *    anchor to "#" navigates and jumps scroll, and `aria-disabled` on a link
 *    still follows on click. First/last page need to be genuinely inert, so
 *    these are real {@code <button>}s with a real `disabled` attribute.
 */

function Pagination({ className, ...props }: ComponentProps<"nav">) {
  return (
    <nav
      role="navigation"
      aria-label="pagination"
      data-slot="pagination"
      className={cn("mx-auto flex w-full justify-center", className)}
      {...props}
    />
  )
}

function PaginationContent({ className, ...props }: ComponentProps<"ul">) {
  return (
    <ul
      data-slot="pagination-content"
      className={cn("flex items-center gap-0.5", className)}
      {...props}
    />
  )
}

function PaginationItem({ ...props }: ComponentProps<"li">) {
  return <li data-slot="pagination-item" {...props} />
}

/** The shared control. `variant`/`size` are this app's Button's, not shadcn's. */
function PaginationButton({ className, ...props }: ComponentProps<typeof Button>) {
  return (
    <Button
      variant="ghost"
      // Use size (not className padding/font, which loses to Button's own
      // size classes in CSS). Before {...props} so a caller can override it.
      size="sm"
      data-slot="pagination-link"
      className={className}
      {...props}
    />
  )
}

function PaginationPrevious({
  className,
  text = "Previous",
  ...props
}: ComponentProps<typeof PaginationButton> & { text?: string }) {
  return (
    <PaginationButton
      aria-label="Go to previous page"
      className={cn("pl-1.5", className)}
      {...props}
    >
      <ChevronLeftIcon className="size-4" aria-hidden />
      <span className="hidden sm:block">{text}</span>
    </PaginationButton>
  )
}

function PaginationNext({
  className,
  text = "Next",
  ...props
}: ComponentProps<typeof PaginationButton> & { text?: string }) {
  return (
    <PaginationButton
      aria-label="Go to next page"
      className={cn("pr-1.5", className)}
      {...props}
    >
      <span className="hidden sm:block">{text}</span>
      <ChevronRightIcon className="size-4" aria-hidden />
    </PaginationButton>
  )
}

function PaginationEllipsis({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      aria-hidden
      data-slot="pagination-ellipsis"
      className={cn("flex size-8 items-center justify-center", className)}
      {...props}
    >
      <MoreHorizontalIcon className="size-4" />
      <span className="sr-only">More pages</span>
    </span>
  )
}

export {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationButton,
  PaginationNext,
  PaginationPrevious,
}
