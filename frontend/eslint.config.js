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
    // Built-in no-restricted-syntax rather than react/jsx-no-literals: this repo
    // has no eslint-plugin-react, and the esquery selectors below enforce the
    // same thing without adding a dependency. The {3,} letter threshold keeps
    // punctuation, separators, and units out of the catalog.
    files: I18N_MIGRATED,
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'JSXText[value=/[A-Za-z]{3,}/]',
          message: 'User-facing text must come from t() — add it to src/i18n/en/<view>.ts.',
        },
        {
          selector:
            'JSXAttribute[name.name=/^(aria-label|aria-description|placeholder|title|alt)$/] > Literal[value=/[A-Za-z]{3,}/]',
          message: 'Accessible and attribute copy must come from t().',
        },
      ],
    },
  },
)
