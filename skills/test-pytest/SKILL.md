---
name: test-pytest
description: pytest 测试生成与缺陷报告规范
---

# 测试规范

## 后端测试
- 文件放 `tests/test_<module>.py`
- 使用 pytest，函数名 `test_<场景>`
- 覆盖: 正常流程、空参数、边界值

## 必测场景（认证模块）
- register 返回用户信息
- login 空密码返回 None 或 400
- routes.py 包含契约中的路径字符串

## 缺陷 defects 格式
```json
{"id": "D-001", "module": "backend|frontend", "desc": "...", "severity": "high|medium|low"}
```

## 通过标准
- defects 为空 → passed=true
- 任一 high 缺陷 → passed=false
