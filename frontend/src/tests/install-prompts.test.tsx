import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PromptFields } from '../components/install/PromptFields'
import { type Prompt, unanswered } from '../lib/install-prompts'

const p = (over: Partial<Prompt> & { variable: string }): Prompt => ({
  label: over.variable, kind: 'text', sensitive: false, gate: false,
  warnings: [], choices: null, default: null, ...over,
})

// pihole's, verbatim. The wording is the point: an operator has to be able to
// read that upstream does not audit this before ticking anything.
const GATE = p({
  variable: 'confirm', gate: true, kind: 'yesno', default: 'n',
  label: 'Do you want to continue? [y/N]:',
  warnings: [
    'WARNING: This script will run an external installer from a third-party source (https://pi-hole.net/).',
    'The following code is NOT maintained or audited by our repository.',
  ],
})

describe('unanswered', () => {
  it('holds Install until a gate is actually ticked', () => {
    expect(unanswered([GATE], {})).toEqual(['confirm'])
    expect(unanswered([GATE], { confirm: 'n' })).toEqual(['confirm'])
    expect(unanswered([GATE], { confirm: 'y' })).toEqual([])
  })

  it('lets a yes/no or a defaulted field through unanswered', () => {
    // These are filled in server side from the recorded default, which is what
    // the 26 no-dialog apps depend on.
    const yesno = p({ variable: 'unbound', kind: 'yesno', default: 'n' })
    const defaulted = p({ variable: 'ml_type', default: '1' })
    expect(unanswered([yesno, defaulted], {})).toEqual([])
  })

  it('holds Install for a field with nothing to fall back on', () => {
    const key = p({ variable: 'tmdbkey', sensitive: true, label: 'Enter your TMDb API key:' })
    const choice = p({ variable: 'ver', kind: 'choice', choices: ['15', '16'] })
    expect(unanswered([key, choice], {}).sort()).toEqual(['tmdbkey', 'ver'])
    expect(unanswered([key, choice], { tmdbkey: 'abc', ver: '16' })).toEqual([])
    // Whitespace is not an answer.
    expect(unanswered([key], { tmdbkey: '   ' })).toEqual(['tmdbkey'])
  })
})

describe('PromptFields', () => {
  it('renders the upstream warning verbatim, not a paraphrase', () => {
    render(<PromptFields prompts={[GATE]} answers={{}} onChange={vi.fn()} />)
    for (const w of GATE.warnings) {
      expect(screen.getByText(w)).toBeInTheDocument()
    }
  })

  it('starts a gate unticked, whatever default the script declared', () => {
    // The script says the default is "n", and even a script that said "y"
    // would not get a pre-ticked box: pre-ticking is defaulting to yes with
    // extra steps.
    render(<PromptFields prompts={[GATE, { ...GATE, variable: 'other', default: 'y' }]}
                         answers={{}} onChange={vi.fn()} />)
    for (const box of screen.getAllByRole('checkbox')) {
      expect(box).not.toBeChecked()
    }
  })

  it('answers a gate with y only when ticked, and clears it when unticked', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <PromptFields prompts={[GATE]} answers={{}} onChange={onChange} />)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalledWith({ confirm: 'y' })

    rerender(<PromptFields prompts={[GATE]} answers={{ confirm: 'y' }} onChange={onChange} />)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenLastCalledWith({ confirm: '' })
  })

  it('masks a sensitive field and says where the value goes', () => {
    const key = p({ variable: 'tmdbkey', sensitive: true, label: 'Enter your TMDb API key:' })
    render(<PromptFields prompts={[key]} answers={{}} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Enter your TMDb API key:')).toHaveAttribute('type', 'password')
    expect(screen.getByText(/stored encrypted/i)).toBeInTheDocument()
  })

  it('leaves an ordinary field unmasked', () => {
    const name = p({ variable: 'servername', label: 'Please enter the name for your server:' })
    render(<PromptFields prompts={[name]} answers={{}} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Please enter the name for your server:'))
      .toHaveAttribute('type', 'text')
  })

  it('offers a choice as a select rather than a box to guess into', () => {
    // docker's, which is the reason choices matter: "insecure" has to survive
    // into the label, and the three options are not guessable.
    const socket = p({
      variable: 'socket_choice', kind: 'choice', choices: ['n', 'l', 'a'],
      label: 'Expose Docker TCP socket (insecure) ? [n = No, l = Local only] <n/l/a>:',
    })
    render(<PromptFields prompts={[socket]} answers={{}} onChange={vi.fn()} />)
    const select = screen.getByLabelText(/Expose Docker TCP socket \(insecure\)/)
    expect(select.tagName).toBe('SELECT')
    expect(screen.getByRole('option', { name: 'l' })).toBeInTheDocument()
  })

  it('shows the script author\'s own sentence, never a rewrite', () => {
    const odd = p({ variable: 'prompt', label: 'Please paste an identity enrollment token(JTW)',
                    sensitive: true })
    render(<PromptFields prompts={[odd]} answers={{}} onChange={vi.fn()} />)
    // Including the typo. It is upstream's text and not ours to correct.
    expect(screen.getByText('Please paste an identity enrollment token(JTW)')).toBeInTheDocument()
  })

  it('renders nothing at all for an app that asks nothing', () => {
    const { container } = render(
      <PromptFields prompts={[]} answers={{}} onChange={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })
})
