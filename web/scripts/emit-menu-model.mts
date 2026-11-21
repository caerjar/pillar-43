/**
 * Emit the native menu's data half as JSON.
 *
 * Run by `scripts/codegen-menu`, never by hand. Lives outside `src/` so it is
 * not bundled, linted as app code, or picked up by the vitest globs.
 *
 * Only labels, ids and accelerators cross into Rust — `run` is behaviour and
 * stays in TypeScript, so the host actions are stubbed here.
 */
import { buildMenus } from '../src/lib/menu/menuModel'

const noop = () => {}
const menus = buildMenus({
  openSearch: noop,
  openCommandPalette: noop,
  goBack: noop,
  goForward: noop,
})

console.log(
  JSON.stringify(
    {
      _generated:
        'scripts/codegen-menu from web/src/lib/menu/menuModel.ts — do not edit',
      menus: menus.map((m) => ({
        id: m.id,
        label: m.label,
        items: m.items.map((i) =>
          i === 'separator'
            ? 'separator'
            : {
                id: i.id,
                label: i.label,
                ...(i.accelerator ? { accelerator: i.accelerator } : {}),
              },
        ),
      })),
    },
    null,
    2,
  ),
)
