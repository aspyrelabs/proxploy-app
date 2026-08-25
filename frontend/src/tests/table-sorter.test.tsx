/**
 * Sorting the Apps and VMs lists, and the three things about it that are not
 * obvious: status is ordered by urgency rather than by the alphabet, names are
 * compared the way a human reads them, and equal keys never swap places.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { STATUS_ORDER, TableSorter, sortRows, useSorted } from '../components/TableSorter'

const row = (name: string, host_name = 'node1', status = 'running') =>
  ({ name, host_name, status })

const names = (rows: { name: string }[]) => rows.map((r) => r.name)

/** Drives useSorted + TableSorter the way both pages do. */
function Harness({ rows }: { rows: ReturnType<typeof row>[] }) {
  const sorted = useSorted(rows)
  return (
    <>
      <ul>{sorted.rows.map((r) => <li key={r.name}>{r.name}</li>)}</ul>
      <TableSorter sort={sorted.sort} onSort={sorted.setSort} label="apps" />
    </>
  )
}

describe('table sorting', () => {
  it('leaves the API order alone until an order is chosen', () => {
    // The whole point of the `none` default: a page that renders the control
    // and changes nothing else looks exactly as it did before.
    const rows = [row('zulu'), row('alpha'), row('mike')]
    expect(sortRows(rows, 'none')).toBe(rows)
  })

  it('sorts by name', () => {
    const rows = [row('zulu'), row('alpha'), row('mike')]
    expect(names(sortRows(rows, 'name'))).toEqual(['alpha', 'mike', 'zulu'])
  })

  it('sorts by host', () => {
    const rows = [row('a', 'node3'), row('b', 'node1'), row('c', 'node2')]
    expect(names(sortRows(rows, 'host'))).toEqual(['b', 'c', 'a'])
  })

  it('sorts by status, and not alphabetically', () => {
    // Alphabetical would be paused, running, stopped, unknown, which buries
    // what is up under what is not. Urgency order leads with running.
    expect(STATUS_ORDER).toEqual(['running', 'paused', 'stopped', 'unknown'])
    const rows = [row('a', 'n', 'stopped'), row('b', 'n', 'unknown'),
                  row('c', 'n', 'paused'), row('d', 'n', 'running')]
    expect(sortRows(rows, 'status').map((r) => r.status))
      .toEqual(['running', 'paused', 'stopped', 'unknown'])
  })

  it('puts a status nobody has a rank for at the bottom', () => {
    // A state PVE invents later is something we cannot rank, and the bottom is
    // where it can be seen rather than mixed in with the running guests.
    const rows = [row('a', 'n', 'hibernating'), row('b', 'n', 'unknown'),
                  row('c', 'n', 'running')]
    expect(names(sortRows(rows, 'status'))).toEqual(['c', 'b', 'a'])
  })

  it('compares names without caring about case', () => {
    // Raw code points put every capital ahead of every lowercase letter, so
    // Plex sorted above immich and the list read as broken.
    const rows = [row('Plex'), row('immich'), row('Adguard')]
    expect(names(sortRows(rows, 'name'))).toEqual(['Adguard', 'immich', 'Plex'])
  })

  it('breaks a tie on name so equal keys hold still', () => {
    // Three apps on one host, arriving in whatever order the poller wrote
    // them. Without the tiebreak these keep their input order, which the next
    // poll is free to change, and rows swap places under the cursor.
    const rows = [row('sonarr', 'node1'), row('adguard', 'node1'), row('plex', 'node1')]
    expect(names(sortRows(rows, 'host'))).toEqual(['adguard', 'plex', 'sonarr'])
    // And the same input in a different order lands the same way.
    expect(names(sortRows([...rows].reverse(), 'host')))
      .toEqual(['adguard', 'plex', 'sonarr'])
  })

  it('reorders the list when the control is used', () => {
    render(<Harness rows={[row('zulu'), row('alpha'), row('mike')]} />)
    const select = screen.getByRole('combobox', { name: 'Sort apps' })
    expect(screen.getAllByRole('listitem').map((l) => l.textContent))
      .toEqual(['zulu', 'alpha', 'mike'])
    fireEvent.change(select, { target: { value: 'name' } })
    expect(screen.getAllByRole('listitem').map((l) => l.textContent))
      .toEqual(['alpha', 'mike', 'zulu'])
  })
})
