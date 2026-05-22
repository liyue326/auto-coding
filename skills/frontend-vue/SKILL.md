---
name: frontend-vue
description: Vue 3 前端结构与编码规范
---

# Vue 3 前端规范

## 目录结构
```
frontend/
├── src/
│   ├── api/           # axios 或 fetch 封装
│   ├── views/         # 页面 *.vue
│   ├── router/index.js
│   └── App.vue
└── package.json       # 可选
```

## 组件规范
- 使用 `<script setup>` + Composition API
- 单文件组件: `views/LoginView.vue`
- 表单字段与 api_contract body 字段名一致

## 请求封装
- `src/api/auth.js` 导出 `register()`、`login()`
- baseURL: `import.meta.env.VITE_API_BASE || 'http://localhost:8000'`

## 交互
- 密码框: `type="password"`
- 提交中禁用按钮，展示 loading
- 捕获错误并 `alert` 或页面提示

## 路由
```js
{ path: '/login', component: () => import('../views/LoginView.vue') }
```
