import ReactMarkdown from 'react-markdown'

/**
 * Renders a small, fixed subset of markdown from UNTRUSTED third-party text.
 *
 * The content this exists for is GitHub release notes, written by whoever
 * maintains the app upstream. It was rendered as literal characters in a
 * <pre> precisely because turning attacker-influenced text into HTML is an
 * XSS hole, and that concern has not gone away; it has been answered.
 *
 * WHY react-markdown, and why no sanitizer alongside it. The usual pairing is
 * a markdown compiler plus DOMPurify, but that shape only exists because the
 * compiler emits an HTML STRING which then has to be cleaned and injected
 * with dangerouslySetInnerHTML. react-markdown never produces a string: it
 * parses to an AST and renders React ELEMENTS, so every text node is escaped
 * by React itself and there is no innerHTML anywhere in this file. That
 * removes the injection sink rather than filtering what flows into it, which
 * is a stronger property than any denylist and one less dependency to keep
 * patched. Raw HTML in the source is inert by default too: passing it through
 * would require adding rehype-raw, which is deliberately not installed.
 *
 * The remaining sink is the href on a link, which React will happily set to
 * `javascript:...`. That is what `safeUrl` below closes.
 *
 * DEFAULT export, and lazily imported by its only caller. react-markdown
 * and its unified/micromark tree are 35.7 kB gzipped, which is a lot to put
 * on every page load for a box that renders only inside an app's detail
 * view. React.lazy needs a default export, so that is what it gets.
 *
 * Everything here is an ALLOWLIST. `allowedElements` names what may render;
 * anything else (an <img>, a <table>, raw HTML that a future rehype plugin
 * might introduce) is dropped, with `unwrapDisallowed` keeping its text so a
 * reader still sees the words rather than a silent gap.
 */

// Headings, emphasis, lists, code, links, paragraphs. That is the realistic
// surface of a release note. h1/h2 are included because notes often start at
// "# 1.2.0"; they are styled down to fit the panel rather than dropped.
const ALLOWED = [
  'p', 'br', 'hr', 'strong', 'em', 'del',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'ul', 'ol', 'li', 'code', 'pre', 'blockquote', 'a',
]

/**
 * http and https only. Everything else, including `javascript:`, `data:` and
 * relative paths, resolves to no href at all: a link with nowhere safe to go
 * renders as plain text rather than as something clickable that lies about
 * where it leads.
 *
 * Deliberately tighter than react-markdown's own default, which also permits
 * mailto, tel and relative urls. None of those mean anything in a changelog,
 * and a relative href inside a modal would navigate the app itself.
 */
function safeUrl(url: string): string {
  try {
    const scheme = new URL(url, 'https://invalid.example').protocol
    return scheme === 'http:' || scheme === 'https:' ? url : ''
  } catch {
    return ''
  }
}

export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      allowedElements={ALLOWED}
      unwrapDisallowed
      urlTransform={safeUrl}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        h1: ({ children }) => <h4 className="mt-3 mb-1 font-display text-[13px] font-semibold text-text first:mt-0">{children}</h4>,
        h2: ({ children }) => <h4 className="mt-3 mb-1 font-display text-[13px] font-semibold text-text first:mt-0">{children}</h4>,
        h3: ({ children }) => <h5 className="mt-3 mb-1 font-display text-[12.5px] font-semibold text-text first:mt-0">{children}</h5>,
        h4: ({ children }) => <h5 className="mt-3 mb-1 font-display text-[12.5px] font-semibold text-text first:mt-0">{children}</h5>,
        h5: ({ children }) => <h6 className="mt-3 mb-1 font-display text-[12px] font-semibold text-text-2 first:mt-0">{children}</h6>,
        h6: ({ children }) => <h6 className="mt-3 mb-1 font-display text-[12px] font-semibold text-text-2 first:mt-0">{children}</h6>,
        ul: ({ children }) => <ul className="mb-2 list-disc space-y-0.5 pl-4 last:mb-0">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 list-decimal space-y-0.5 pl-4 last:mb-0">{children}</ol>,
        li: ({ children }) => <li className="marker:text-text-3">{children}</li>,
        strong: ({ children }) => <strong className="font-semibold text-text">{children}</strong>,
        blockquote: ({ children }) => (
          <blockquote className="mb-2 border-l-2 border-line pl-2 text-text-3 last:mb-0">{children}</blockquote>
        ),
        hr: () => <hr className="my-3 border-line-soft" />,
        // A fenced block is its own scroller: a release note pasting a wide
        // shell command must not widen the dialog it sits in.
        pre: ({ children }) => (
          <pre className="mb-2 overflow-x-auto rounded-tile border border-line-soft bg-panel p-2 font-mono text-[11px] last:mb-0">
            {children}
          </pre>
        ),
        code: ({ children }) => (
          <code className="rounded bg-panel px-1 font-mono text-[11px] text-text">{children}</code>
        ),
        // safeUrl has already blanked anything that is not http(s), so an
        // empty href here means "this was not a safe link": render the words,
        // not a control.
        a: ({ href, children }) =>
          href
            ? <a href={href} target="_blank" rel="noreferrer noopener"
                className="text-amber hover:underline">{children}</a>
            : <>{children}</>,
      }}
    >
      {children}
    </ReactMarkdown>
  )
}
