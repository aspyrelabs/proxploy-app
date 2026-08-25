/**
 * Paging the two tables on /backups, and the two things about it that are not
 * obvious: what happens when the rows move under you, and how a long list is
 * drawn without a button per page.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { PAGE_SIZE, TablePager, usePaged } from '../components/TablePager'

const nums = (n: number) => Array.from({ length: n }, (_, i) => i + 1)

/** Drives usePaged + TablePager the way both callers do. */
function Harness({ total }: { total: number }) {
  const [count, setCount] = useState(total)
  const paged = usePaged(nums(count))
  return (
    <>
      <button onClick={() => setCount(3)}>shrink</button>
      <ul>{paged.rows.map((r) => <li key={r}>row {r}</li>)}</ul>
      <p>page {paged.page} of {paged.pages}</p>
      <TablePager page={paged.page} pages={paged.pages} onPage={paged.setPage}
                  label="test pages" />
    </>
  )
}

describe('table paging', () => {
  it('shows ten to a page', () => {
    expect(PAGE_SIZE).toBe(10)
    render(<Harness total={25} />)
    expect(screen.getAllByRole('listitem').filter(
      (l) => l.textContent?.startsWith('row'))).toHaveLength(10)
    expect(screen.getByText('page 1 of 3')).toBeInTheDocument()
  })

  it('draws nothing at all for a single page', () => {
    // A pager under ten rows is furniture.
    render(<Harness total={7} />)
    expect(screen.queryByRole('navigation', { name: 'test pages' })).toBeNull()
  })

  it('walks forward and back', () => {
    render(<Harness total={25} />)
    fireEvent.click(screen.getByRole('button', { name: 'Go to next page' }))
    expect(screen.getByText('page 2 of 3')).toBeInTheDocument()
    expect(screen.getByText('row 11')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Go to previous page' }))
    expect(screen.getByText('page 1 of 3')).toBeInTheDocument()
  })

  it('stops at both ends', () => {
    render(<Harness total={25} />)
    expect(screen.getByRole('button', { name: 'Go to previous page' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Go to page 3' }))
    expect(screen.getByRole('button', { name: 'Go to next page' })).toBeDisabled()
  })

  it('marks the page you are on for a screen reader too', () => {
    render(<Harness total={25} />)
    expect(screen.getByRole('button', { name: 'Go to page 1' }))
      .toHaveAttribute('aria-current', 'page')
  })

  it('gaps a long list instead of drawing forty buttons', () => {
    render(<Harness total={400} />)   // 40 pages
    expect(screen.getByRole('button', { name: 'Go to page 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go to page 40' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Go to page 20' })).toBeNull()
    // First, its two neighbours, last, and one gap marker between them.
    expect(screen.getAllByText('More pages')).toHaveLength(1)
  })

  it('clamps back when the rows shrink under the page you are on', () => {
    // A poll can delete rows while you are on page 3 (a prune, a schedule
    // removed elsewhere). Holding the stored page would render an empty table
    // with no way back to the rows that are left.
    render(<Harness total={25} />)
    fireEvent.click(screen.getByRole('button', { name: 'Go to page 3' }))
    expect(screen.getByText('page 3 of 3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'shrink' }))
    expect(screen.getByText('page 1 of 1')).toBeInTheDocument()
    expect(screen.getByText('row 1')).toBeInTheDocument()
  })
})
