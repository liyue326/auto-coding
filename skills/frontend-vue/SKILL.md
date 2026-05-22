---
name: frontend-vue
description: Vue 3 前端结构与编码规范（按需求选用）
---

# Vue 3 前端规范

## 原则
- **以用户原文需求为准**（纯 UI、绘图、单页、多页、对接 API 等均可）
- 无 api_contract 时不要假设后端接口；可用本地状态或静态内容

## 常见目录（按需创建）
```
frontend/
├── src/
│   ├── api/           # 有契约时再封装请求
│   ├── views/         # 多页面
│   ├── components/    # 可复用组件
│   ├── router/index.js
│   └── App.vue        # 单页需求可只改此文件
```

## 组件规范
- 使用 `<script setup>` + Composition API
- 表单字段名与 api_contract 一致（有契约时）
- 密码框使用 `type="password"`（有密码输入时）

## 请求封装（有后端契约时）
- `src/api/<module>.js` 导出与契约一致的函数
- baseURL: `import.meta.env.VITE_API_BASE || 'http://localhost:8000'`

## 交互
- 异步提交时可用 loading 与错误提示
