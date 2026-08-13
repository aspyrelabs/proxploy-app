import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Progress, ProgressLabel, ProgressValue } from '../components/ui/progress'

describe('Progress', () => {
  it('takes its accessible name from ProgressLabel and shows the figure', () => {
    render(
      <Progress value={56} className="w-full max-w-sm">
        <ProgressLabel>Upload progress</ProgressLabel>
        <ProgressValue />
      </Progress>,
    )
    const bar = screen.getByRole('progressbar', { name: 'Upload progress' })
    expect(bar).toHaveAttribute('aria-valuenow', '56')
    expect(bar).toHaveAttribute('aria-valuetext', '56%')
    expect(bar).toHaveAttribute('aria-busy', 'false')
    expect(screen.getByText('56%')).toBeInTheDocument()
  })

  it('is indeterminate with no value, and shows no figure at all', () => {
    // The whole point of the two modes: waiting is not zero percent, and a
    // number nobody reported must never appear (same rule as ui/loading.tsx).
    render(
      <Progress>
        <ProgressLabel>Refreshing the catalog</ProgressLabel>
        <ProgressValue />
      </Progress>,
    )
    const bar = screen.getByRole('progressbar', { name: 'Refreshing the catalog' })
    expect(bar).toHaveAttribute('aria-busy', 'true')
    expect(bar).not.toHaveAttribute('aria-valuenow')
    expect(bar).not.toHaveAttribute('aria-valuetext')
    expect(screen.queryByText(/%/)).toBeNull()
    expect(bar.querySelector('.pp-progress-sweep')).not.toBeNull()
  })

  it('treats an explicit null the same as no value at all', () => {
    // A job row's progress_pct is null before its first report, so null has
    // to mean indeterminate rather than falling through to some default.
    render(<Progress value={null}><ProgressLabel>Working</ProgressLabel></Progress>)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-busy', 'true')
  })

  it('renders zero as a real value rather than as indeterminate', () => {
    render(<Progress value={0}><ProgressValue /></Progress>)
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '0')
    expect(bar).toHaveAttribute('aria-busy', 'false')
    expect(screen.getByText('0%')).toBeInTheDocument()
  })

  it('clamps and rounds whatever it is handed', () => {
    const { rerender } = render(<Progress value={130}><ProgressValue /></Progress>)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    rerender(<Progress value={-5}><ProgressValue /></Progress>)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
    rerender(<Progress value={56.6}><ProgressValue /></Progress>)
    expect(screen.getByText('57%')).toBeInTheDocument()
  })

  it('renders with neither child, as a bare bar', () => {
    render(<Progress value={10} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '10')
    expect(screen.queryByText(/%/)).toBeNull()
  })
})
