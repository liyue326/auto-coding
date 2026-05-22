---
name: test-pytest
description: pytest 测试生成与缺陷报告规范
---

# 测试规范

## 原则
- 测试用例必须**对应当次生成的代码与用户需求**，不要写死登录/注册等固定场景
- 无后端交付时（frontend_only）不要生成后端 pytest

## 后端测试（有 backend 交付时）
- 文件放 `tests/test_<module>.py`
- 使用 pytest，函数名 `test_<场景>`
- 覆盖: 正常流程、空参数、边界值（按实际模块）

## 缺陷 defects 格式
```json
{"id": "D-001", "module": "backend|frontend", "desc": "...", "severity": "high|medium|low"}
```

## 通过标准
- defects 为空 → passed=true
- 任一 high 缺陷 → passed=false
