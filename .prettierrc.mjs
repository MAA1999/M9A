import * as maafwSort from '@nekosu/prettier-plugin-maafw-sort'
import * as multilineArrays from 'prettier-plugin-multiline-arrays'

export default {
  semi: false,
  singleQuote: true,
  trailingComma: 'none',
  tabWidth: 2,
  printWidth: 100,
  multilineArraysWrapThreshold: 0,
  plugins: [
    maafwSort.patchPlugin(multilineArrays)
  ],
  overrides: [
    {
      files: [
        '*.json'
      ],
      options: {
        parser: 'json',
        tabWidth: 4
      }
    },
    {
      files: [
        '*.jsonc'
      ],
      options: {
        parser: 'jsonc',
        tabWidth: 4
      }
    }
  ]
}
