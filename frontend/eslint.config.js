// ESLint 扁平配置（Vue3 + TypeScript）。
//
// 说明：本机是离线环境，装不了 eslint / typescript-eslint / eslint-plugin-vue，
// 所以这份配置**没有**接进 CI（避免"配置写了但从没跑过"）。联网后执行：
//
//   npm i -D eslint @eslint/js typescript-eslint eslint-plugin-vue globals vue-eslint-parser
//   npm run lint
//
// package.json 里已预留 lint 脚本。
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'

export default [
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser, ecmaVersion: 'latest', sourceType: 'module' },
      globals: { window: 'readonly', document: 'readonly', localStorage: 'readonly', console: 'readonly' },
    },
    rules: {
      // 组件的 props/emit 用 TS 类型声明，不需要运行时 prop 校验
      'vue/require-default-prop': 'off',
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
    },
  },
  { ignores: ['dist/**', 'node_modules/**', 'static/**'] },
]
