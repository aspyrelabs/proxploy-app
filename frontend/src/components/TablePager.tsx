import { useState } from 'react'

import {
  Pagination, PaginationContent, PaginationEllipsis, PaginationItem,
  PaginationButton, PaginationNext, PaginationPrevious,
} from './ui/pagination'

/** Rows per page, shared so the two tables on /backups agree. */
export const PAGE_SIZE = 10

/**
 * Six columns pinned so the Scheduled jobs and Recent backups tables line up.
 *
 * `table-fixed` plus one colgroup is what aligns them: auto layout cannot,
 * because the columns hold different things. The last column holds the
 * actions, sized for them and no wider.
 *
 * The cost is that a column no longer grows for its content, so anything long
 * (a guest name, a cron expression) truncates instead of pushing its
 * neighbours around. Cells that can overflow carry `truncate` and a title.
 */
export const SIX_COL = (
  <colgroup>
    <col className="w-[22%]" />
    <col className="w-[13%]" />
    <col className="w-[15%]" />
    <col className="w-[13%]" />
    <col className="w-[11%]" />
    {/* The widest of the six, because it has a hard floor: Recent backups
        puts four buttons here (Verify, Test restore, Restore, Delete) and
        Scheduled jobs three. */}
    <col className="w-[26%]" />
  </colgroup>
)

/** Page a list client-side. The rows are already in memory in both callers, so
 *  this asks the server for nothing.
 *
 *  The page is CLAMPED rather than stored blindly: a poll can delete the rows
 *  under you (a prune, a schedule removed elsewhere) and page 5 of a list that
 *  is now one page long would render empty with no way back. */
export function usePaged<T>(rows: T[], size: number = PAGE_SIZE) {
  const [page, setPage] = useState(1)
  const pages = Math.max(1, Math.ceil(rows.length / size))
  const current = Math.min(Math.max(1, page), pages)
  return {
    page: current,
    pages,
    setPage,
    rows: rows.slice((current - 1) * size, current * size),
  }
}

/** Which page numbers to draw: the ends, the current one and its neighbours,
 *  with a gap marker for whatever that skips. A list of 40 pages must not
 *  render 40 buttons. */
function pageList(page: number, pages: number): (number | 'gap')[] {
  const near = new Set([1, pages, page - 1, page, page + 1])
  const out: (number | 'gap')[] = []
  for (let p = 1; p <= pages; p++) {
    if (near.has(p)) out.push(p)
    else if (out[out.length - 1] !== 'gap') out.push('gap')
  }
  return out
}

/** Nothing at all for a single page: a pager under ten rows is furniture. */
export function TablePager({ page, pages, onPage, label }: {
  page: number
  pages: number
  onPage: (p: number) => void
  /** Named for what is being paged, so two pagers on one screen are told
   *  apart by anyone not looking at them. */
  label: string
}) {
  if (pages <= 1) return null
  return (
    <Pagination className="mt-3" aria-label={label}>
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious disabled={page === 1} onClick={() => onPage(page - 1)} />
        </PaginationItem>
        {pageList(page, pages).map((p, i) => (
          <PaginationItem key={p === 'gap' ? `gap${i}` : p}>
            {p === 'gap' ? <PaginationEllipsis /> : (
              <PaginationButton
                aria-label={`Go to page ${p}`}
                aria-current={p === page ? 'page' : undefined}
                variant={p === page ? 'go' : 'ghost'}
                onClick={() => onPage(p)}>
                {p}
              </PaginationButton>
            )}
          </PaginationItem>
        ))}
        <PaginationItem>
          <PaginationNext disabled={page === pages} onClick={() => onPage(page + 1)} />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  )
}
