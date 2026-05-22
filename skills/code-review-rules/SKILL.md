---
name: code-review-rules
description: 全栈代码评审检查清单与评分规则
---

# 代码评审检查清单

## 必查项（high）
- [ ] 存在 `api/routes.py` 且路由与 api_contract 一致
- [ ] 存在 `schema.sql` 用户/业务表
- [ ] 前端 `src/api/` 覆盖契约中所有端点
- [ ] 后端无明文密码存储（应有 password_hash）
- [ ] 前端密码输入 `type="password"`

## 建议项（medium）
- [ ] 服务层与路由层分离
- [ ] Vue 使用 router 注册页面
- [ ] 异常处理完整（HTTPException）

## 评分参考
| 分数 | 含义 |
|------|------|
| 85-100 | 规范、安全、契约一致 |
| 70-84 | 小问题，可上线前修复 |
| 60-69 | 有 medium 问题 |
| <60 | 缺关键文件或 high 问题 |

## passed 判定
- score >= 通过阈值 且 无 high 问题 → passed=true
- 禁止对结构完整项目给出 score=0
