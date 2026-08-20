import { Fragment } from 'react'
import { APPS_VIEWS, type AppsView } from '../lib/apps-view'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { Icon } from './ui/icon'

const ORDER: AppsView[] = ['detailed', 'list', 'icon']

/**
 * Which presentation the Apps section draws, as three welded icon buttons.
 *
 * aria-pressed rather than colour alone: these are icon-only toggles, and
 * which one is active has to be readable to a screen reader and to anyone who
 * cannot pick the active tint out of three otherwise identical buttons.
 */
export function AppsViewSwitch({ value, onChange }: {
  value: AppsView
  onChange: (v: AppsView) => void
}) {
  return (
    <ButtonGroup>
      {ORDER.map((v, i) => (
        // An explicit keyed Fragment, not `<>`: the shorthand takes no key,
        // and a keyless child in a map is a React warning that oxlint fails on.
        <Fragment key={v}>
          {i > 0 && <ButtonGroupSeparator />}
          <Button size="icon-xs"
            variant={v === value ? 'go' : 'ghost'}
            aria-pressed={v === value}
            aria-label={APPS_VIEWS[v].label}
            title={APPS_VIEWS[v].label}
            onClick={() => onChange(v)}>
            <Icon name={APPS_VIEWS[v].icon} size={16} />
          </Button>
        </Fragment>
      ))}
    </ButtonGroup>
  )
}
