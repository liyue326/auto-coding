---
name: code-review-rules
description: 全栈代码评审检查清单与评分规则
---

# 代码评审检查清单

## 必查项（high，按 dev_scope）
- [ ] 本次 scope 要求的前端/后端是否**有实际交付文件**（非空）
- [ ] 若代码涉及密码：后端无明文落库；前端密码框 `type="password"`
- [ ] 若存在 api_contract：前后端路径/字段与契约一致

## 建议项（medium）
- [ ] 结构清晰、命名可读
- [ ] FastAPI 路由有基本异常处理（存在 api/routes.py 时）

## 不要做的事
- 不要因「缺少 schema.sql / src/api/ / LoginView」等固定文件名扣分（除非用户需求明确要求）
- frontend_only 时不要因缺少后端文件扣分

## 评分参考
| 分数 | 含义 |
|------|------|
| 85-100 | 符合需求、规范、安全 |
| 70-84 | 小问题，可上线前修复 |
| 60-69 | 有 medium 问题 |
| <60 | 未交付或 high 问题 |

## passed 判定
- score >= 通过阈值 且 无 high 问题 → passed=true
- 禁止对结构完整项目给出 score=0
