import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL as NodeURL } from 'node:url'
import { LoginForm } from '../components/LoginForm'

describe('tokens', () => {
  it('ships the prototype values verbatim (doc 06 §c)', () => {
    const css = readFileSync(fileURLToPath(new NodeURL('../styles/tokens.css', import.meta.url)), 'utf8')
    for (const hex of ['#0B0F16', '#121924', '#F5B544', '#3FCF8E', '#F26D6D',
                       '#5B9DF9', '#A78BFA', '#34D3C6', '#E8EDF4'])
      expect(css).toContain(hex)
    expect(css).toContain("'Space Grotesk'")
    expect(css).toContain("'JetBrains Mono'")
  })
})

describe('LoginForm', () => {
  it('renders brand + email/password fields', () => {
    render(<LoginForm onSuccess={() => {}} />)
    expect(screen.getByText(/Prox/)).toBeDefined()
    expect(screen.getByLabelText(/email/i)).toBeDefined()
    expect(screen.getByLabelText(/password/i)).toBeDefined()
  })
})
