// Flat-config ESLint setup for the Pillar-43 web frontend.
//
// Gated at BOTH the pre-commit hook and CI with --max-warnings=11.
//
// The ceiling is a ratchet: it may only ever go down. History, so the number
// stays legible: 61 (stale, admitted 25 warnings that did not exist) -> 36
// (measured) -> 44 (exhaustive-deps switched on) -> 91 (jsx-a11y switched on,
// surfacing 53 pre-existing defects) -> 39 (those 53 fixed) -> 11 (hex
// literals mapped onto design tokens).
//
// Counts below are measured, not estimated. Re-measure before editing this
// comment — a stale note here is worse than no note.
//
// The 11, by rule:
//   - max-lines (>600 effective lines): 6 — App.tsx (609), AISidebar (605),
//     Editor (749), TreeNodeRow (765), MaintainPanel (1015), and the
//     generated API client (7437, which is codegen and will never shrink).
//     App.tsx crossed the line in the a11y pass, by 8 lines, to give the AI
//     sidebar keyboard resizing. Noted rather than hidden.
//   - no-restricted-syntax (hex literals in JSX style props): 3, all of them
//     deliberate and each carrying its reason inline at the call site:
//     Editor.tsx's white paper sheet (must not follow the theme), and the
//     #7b0000 on DetritusCard/DuplicateCard, which is a darker second tier of
//     red reserved for irreversible delete — folding it into var(--error)
//     would erase a severity distinction, not clean anything up.
//     The other 28 became tokens; 16 of them were #fff on an accent
//     background, which had no token at all until --on-accent was added.
//   - react-hooks/exhaustive-deps: 2 (GraphView, HomePanel — both untested,
//     so changing hook dependencies there needs tests written first)
//
// The number appears in four files: here, .pre-commit-config.yaml, and both
// workflows in .github/workflows/. Change them together.
//
// jsx-a11y is at ZERO and should stay there. Where a finding was legitimately
// not a control — a hover wrapper, a drop zone, a modal backdrop, an
// event-delegation root — it carries an inline disable WITH its reason rather
// than sitting in this count forever.
//
// Run with: cd web && npx eslint src/

import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import globals from 'globals'

export default tseslint.config(
  {
    // Test files were excluded here. They are 25 files of a public repo's
    // example surface, and they lint clean today (measured: 0 messages), so
    // the only cost of including them is keeping them clean.
    ignores: ['dist/**', 'node_modules/**', 'coverage/**'],
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
    ],
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'jsx-a11y': jsxA11y,
    },
    linterOptions: {
      // A disable comment for a rule that is off suppresses nothing and reads
      // as though a real exception is in force. Four such no-ops had already
      // accumulated. Reporting them keeps suppressions honest.
      reportUnusedDisableDirectives: 'error',
    },
    languageOptions: {
      ecmaVersion: 2022,
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      // Gated guards. Pre-commit caps total warnings at 61, so adding a new
      // offender to any of these blocks the commit. Promote each to 'error'
      // after a dedicated sweep reduces its count to zero.
      'no-restricted-syntax': [
        'warn',
        {
          // Hex literals in JSX style props — use --eon-* design tokens or
          // CSS custom properties instead so themes work end-to-end.
          selector:
            "JSXAttribute[name.name='style'] Literal[value=/^#[0-9a-fA-F]{3,8}$/]",
          message:
            'Use design tokens (var(--eon-*) / var(--accent), etc.) instead of hex literals in style props.',
        },
      ],
      'max-lines': [
        'warn',
        { max: 600, skipBlankLines: true, skipComments: true },
      ],

      // Zero violations each, measured across src/ AND the test files. These
      // were 'off' on the assumption they'd "light up hundreds of legacy
      // sites"; they don't light up any. On, as errors.
      '@typescript-eslint/no-empty-object-type': 'error',
      'no-empty': 'error',
      'no-empty-pattern': 'error',
      'no-useless-escape': 'error',
      'no-control-regex': 'error',
      'no-misleading-character-class': 'error',
      'no-prototype-builtins': 'error',
      'prefer-const': 'error',
      'no-cond-assign': 'error',
      'no-irregular-whitespace': 'error',
      // Superseded by the typescript-eslint version; the base rule reports
      // false positives on type-only references.
      'no-unused-vars': 'off',

      // Still off, each for a stated reason rather than inertia:
      // 8 sites in src + 4 in tests. Worth a sweep, but every one is a real
      // decision about a type, not a mechanical fix.
      '@typescript-eslint/no-explicit-any': 'off',
      // On, with the underscore convention the codebase already uses for
      // parameters that exist to satisfy a signature. With that configured the
      // real cost was a single unused catch binding, not the "hundreds of
      // legacy sites" this was assumed to cost.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'all' },
      ],
      // 32 sites, and most are no-op callback defaults where an empty arrow IS
      // the correct value. This one should probably stay off permanently.
      '@typescript-eslint/no-empty-function': 'off',

      // ── Accessibility ───────────────────────────────────────────────────
      // Nothing enforced a11y before, and it showed: 28 clickable div/span
      // elements against 4 tabIndex attributes in the whole tree, i.e. almost
      // every one of them unreachable by keyboard and invisible to a screen
      // reader. That matters more now the repo is public.
      //
      // 'error' where the count is already zero — free, and it stays free:
      'jsx-a11y/alt-text': 'error',              // all 6 <img> already pass
      'jsx-a11y/aria-props': 'error',
      'jsx-a11y/aria-unsupported-elements': 'error',
      'jsx-a11y/role-has-required-aria-props': 'error',
      'jsx-a11y/no-redundant-roles': 'error',
      // 'warn' where there is a real backlog, gated by the ratchet below.
      // Each one is a keyboard user who cannot reach a control, so these are
      // meant to be worked down, not parked:
      'jsx-a11y/click-events-have-key-events': 'warn',
      'jsx-a11y/no-static-element-interactions': 'warn',
      'jsx-a11y/interactive-supports-focus': 'warn',

      // Reports 0, and a violation is always a real bug — hooks called
      // conditionally corrupt React's hook ordering. Error.
      'react-hooks/rules-of-hooks': 'error',
      // 'warn', not off: three disable comments for this rule already existed
      // in App.tsx, AISidebar.tsx and Editor.tsx — written by authors who hit
      // the problem and decided. With the rule off they suppressed nothing.
      // Turning it on activates decisions already made rather than forcing a
      // flag day. The 8 remaining sites are warnings under the ratchet until
      // each gets individual review; a stale-closure bug is not something to
      // leave undetected in the meantime.
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
)
