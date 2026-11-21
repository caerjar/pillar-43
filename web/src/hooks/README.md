# hooks/ — custom React hooks

One line per hook. Use this to discover what's available instead of `ls`-ing.

| Hook | What it does |
|---|---|
| `useStructuredErrorAlert` | Routes classified backend errors (`billing_exhausted`, `authentication_error`, `model_not_found_error`, `rate_limit_error`, `provider_connection_error`) to the right toast tone + sticky/auto + CTA. Old name `useBillingAlert` re-exported for compat. |
| `useGlobalKeyboard` | App-wide keyboard combo handler (⌘K, ⌘P, ⌘⇧F, etc.). Combo strings documented at top of file. |
| `useViewport` | Live viewport breakpoint state — recomputes on window resize. |

When adding a hook: file is `hooks/<name>.ts(x)`, with a JSDoc block on the exported hook explaining what + why. Add a row here.
