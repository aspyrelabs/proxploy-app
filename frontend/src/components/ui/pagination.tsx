import type { ComponentProps } from "react"
import { ChevronLeftIcon, ChevronRightIcon, MoreHorizontalIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

/**
 * shadcn/ui `pagination`, vendored by `npx shadcn@latest add pagination` and
 * then adapted in exactly two places. Everything else (the nav/ul/li
 * structure, the data-slot attributes, the class lists) is upstream's.
 *
 * 1. Upstream renders each control as `<Button asChild variant="outline"
 *    size="icon"><a href="..."/></Button>`. This project has its own
 *    hand-written components/ui/button.tsx that predates shadcn: it has no
 *    `asChild`, and its variants are primary/ghost/danger/go with sizes
 *    md/icon-xs, so upstream's call would have passed `asChild` straight
 *    through to the DOM and asked for a variant and a size that do not
 *    exist. `shadcn add` offered to overwrite button.tsx to fix that from
 *    its end; it was declined, because every other route in the app renders
 *    through that Button and its API is not shadcn's to change. So the
 *    adaptation happens here, in the new file, rather than there, in the
 *    old one.
 *
 * 2. Upstream's controls are anchors, because the registry example is a
 *    static demo where `href="#"` stands in for a real route. An anchor to
 *    "#" navigates and jumps the scroll position, and it cannot be
 *    meaningfully disabled: `aria-disabled` on a link still follows on
 *    click. The first and last page need a control that is genuinely
 *    inert, so these are real `<button>` elements with a real `disabled`
 *    attribute, which is also what makes them announce correctly and pick
 *    up the existing Button's disabled styling for free.
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

/** The shared control. `variant`/`size` are this app's Button's own, not
 *  shadcn's, for the reason in the header note. */
function PaginationButton({ className, ...props }: ComponentProps<typeof Button>) {
  return (
    <Button
      variant="ghost"
      // size, not padding/font in the className: those collide with Button's
      // own size classes and lose in the emitted CSS, so this control was
      // rendering at full `md` rather than the compact one it reads as. Before
      // {...props} so a caller can still choose a different size.
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
