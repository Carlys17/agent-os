import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

// Files whose user-facing copy has been moved into src/i18n (issue #138).
// This list IS the migration ledger: a view joins it in the same change that
// extracts its strings, and can never silently regress afterwards. Views that
// have not been migrated yet stay out, so the rule below is never noise.
const I18N_MIGRATED = [
  'src/app/**/*.tsx',
  'src/components/**/*.tsx',
  'src/views/approvals/**/*.tsx',
  'src/views/env/**/*.tsx',
  'src/views/health/**/*.tsx',
  'src/views/logs/**/*.tsx',
  'src/views/overview/**/*.tsx',
  'src/views/settings/**/*.tsx',
]

// #258: t() reads the locale at call time, so calling it at module scope
// resolves the string once — at module evaluation — and freezes it for the life
// of the page. Every user-facing string must be produced inside a function (a
// component, a helper, a getter) that re-runs after a locale change. The :not()
// clauses spell out "this call has no function ancestor".
const NO_MODULE_SCOPE_T = {
  selector: [
    'CallExpression[callee.name=/^t(Plural)?$/]',
    ':not(FunctionDeclaration CallExpression)',
    ':not(FunctionExpression CallExpression)',
    ':not(ArrowFunctionExpression CallExpression)',
    ':not(MethodDefinition CallExpression)',
    ':not(PropertyDefinition CallExpression)',
  ].join(''),
  message:
    'Module-scope t() freezes the string at module-evaluation time (#258). Move it inside a function so it re-resolves after a locale change.',
}

// Built-in no-restricted-syntax rather than react/jsx-no-literals: this repo
// has no eslint-plugin-react, and the esquery selectors below enforce the same
// thing without adding a dependency. The {3,} letter threshold keeps
// punctuation, separators, and units out of the catalog.
const NO_HARDCODED_COPY = [
  {
    selector: 'JSXText[value=/[A-Za-z]{3,}/]',
    message: 'User-facing text must come from t() — add it to src/i18n/en/<view>.ts.',
  },
  {
    selector:
      'JSXAttribute[name.name=/^(aria-label|aria-description|placeholder|title|alt)$/] > Literal[value=/[A-Za-z]{3,}/]',
    message: 'Accessible and attribute copy must come from t().',
  },
]

export default tseslint.config(
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      '@typescript-eslint/no-explicit-any': 'error',
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}'],
    // no-restricted-syntax is replaced, not merged, by a later config that also
    // sets it — so the migrated-view block below repeats this entry.
    rules: { 'no-restricted-syntax': ['error', NO_MODULE_SCOPE_T] },
  },
  {
    files: I18N_MIGRATED,
    ignores: ['**/*.test.{ts,tsx}'],
    rules: { 'no-restricted-syntax': ['error', NO_MODULE_SCOPE_T, ...NO_HARDCODED_COPY] },
  },
)
