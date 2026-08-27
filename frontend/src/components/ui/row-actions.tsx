import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Button } from './button'
import { Icon } from './icon'

const itemCls = 'flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text '
             + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'

const destructiveItemCls = 'flex w-full cursor-pointer items-center gap-2 border-t border-line-soft '
                         + 'px-3 py-2 text-[13px] text-red outline-none data-[highlighted]:bg-red-dim '
                         + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'

export type RowAction = {
  label: string
  icon: string
  onSelect: () => void
  disabled?: boolean
  title?: string
  destructive?: boolean
}

export function RowActionsMenu({ label, actions }: { label: string; actions: RowAction[] }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button variant="ghost" size="sm" aria-label={label}
          onClick={(e) => e.stopPropagation()}>
          <Icon name="more_vert" size={16} />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6}
          className="z-50 w-48 overflow-hidden rounded-card border border-line bg-panel
                     shadow-[0_12px_32px_rgba(0,0,0,.35)]">
          {actions.map((a) => (
            <DropdownMenu.Item key={a.label}
              className={a.destructive ? destructiveItemCls : itemCls}
              disabled={a.disabled} title={a.title}
              onSelect={a.onSelect}>
              <Icon name={a.icon} size={16} />
              {a.label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
