# 多智能体协作开发系统

基于 **LangGraph** 的多工程师角色流水线：Supervisor 调度 → 前后端并行开发 → 代码评审 → 自动化测试 → 缺陷修复循环 → 交付输出。

**技术栈**：Python FastAPI 后端 + Vue 3 前端

---

## 目录结构

```
u/
├── config.py          # 全局配置（读取 .env）
├── prompts.py         # 各 Agent 的 Prompt 模板
├── pipeline.py        # LangGraph 流水线核心 + CLI 入口
├── app.py             # Streamlit 可视化界面
├── requirements.txt   # Python 依赖
├── .env               # 本地配置（API Key、合并目录等，勿提交 Git）
├── skills/            # 各角色 Skill 规范（评审、API 契约、Vue 等）
└── output/            # 每次运行的独立产出目录
```

---

## 环境要求

- Python 3.9+
- 可访问大模型 API（默认阿里云通义 DashScope 兼容接口）

---

## 快速开始

### 1. 安装依赖

```bash
cd /Users/liyue/Desktop/u
python3 -m pip install -r requirements.txt
```

### 2. 配置 `.env`

在项目根目录创建或编辑 `.env`：

```env
# 大模型（通义示例）
OPENAI_API_KEY=你的API密钥
USE_MOCK_LLM=false
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-turbo

# 无 API Key 时可演示（模板代码，非真实 LLM）
# USE_MOCK_LLM=true

# 交付后合并到主项目
MERGE_ENABLED=true
MERGE_TARGET_ROOT=/Users/liyue/Desktop/all
MERGE_BACKEND_SUBDIR=backend
MERGE_FRONTEND_SUBDIR=frontend
MERGE_OVERWRITE=true
MERGE_CONFLICT_MODE=overwrite
```

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | API 密钥 |
| `OPENAI_BASE_URL` | 兼容 OpenAI 的接口地址 |
| `LLM_MODEL` | 模型名，如 `qwen-turbo`、`qwen-plus` |
| `USE_MOCK_LLM` | `false` 走真实 API；`true` 本地 Mock |
| `MERGE_TARGET_ROOT` | 主项目根目录（合并目标） |
| `MERGE_ENABLED` | `true` 交付后自动合并 |
| `MERGE_BACKEND_SUBDIR` | 后端子目录名，默认 `backend` |
| `MERGE_FRONTEND_SUBDIR` | 前端子目录名，默认 `frontend` |
| `MERGE_OVERWRITE` | `true` 时默认**覆盖**主项目中已存在文件 |
| `MERGE_CONFLICT_MODE` | `overwrite` / `manual` / `skip` / `backup` |

### 3. 启动方式

#### 方式 A：可视化界面（推荐）

```bash
python3 -m streamlit run app.py
```

浏览器打开：**http://localhost:8501**

操作步骤：

1. 在「业务需求」输入框填写需求
2. 侧边栏可配置：输出目录、合并主项目路径、存量项目路径
3. 点击 **「▶ 启动流水线」**
4. 页面实时显示流式日志、评审得分、各 Agent 产出
5. 完成后查看 `output/run_xxx/` 或合并后的主项目目录

#### 方式 B：命令行

```bash
# 基本运行
python3 pipeline.py -r "实现用户注册登录，含 FastAPI 与 Vue3 页面"

# 指定存量项目（只读扫描，不修改原目录）
python3 pipeline.py -r "你的需求" -l /path/to/old-project

# 指定输出根目录
python3 pipeline.py -r "你的需求" -o ./output

# 指定合并目标
python3 pipeline.py -r "你的需求" -m /Users/liyue/Desktop/all

# 只输出到 output，不合并主项目
python3 pipeline.py -r "你的需求" --no-merge
```

---

## 流水线说明

```text
Supervisor（任务拆分 + API 契约）
    ↓ 并行
BackendDev（Python FastAPI）  +  FrontendDev（Vue 3）
    ↓ 汇合
CodeReview（代码评审）
    ↓ 通过 → TestAgent（测试）→ 有缺陷 → BugFix → 复测
    ↓ 通过
Deliver（写入 output + 可选合并主项目）
```

| Agent | 职责 |
|-------|------|
| Supervisor | 拆分任务、定义 API 契约 |
| BackendDev | `models/`、`services/`、`api/routes.py`、`schema.sql` |
| FrontendDev | `src/api/`、`src/views/*.vue`、`src/router/` |
| CodeReview | 规范、安全、契约一致性评分 |
| TestAgent | pytest 用例、缺陷清单 |
| BugFix | 按缺陷修复，进入复测循环 |

---

## 产出目录

### 独立输出（每次运行）

```
output/run_20260522_183045/
├── backend/              # Python 后端代码
├── frontend/             # Vue 前端代码
└── reports/
    └── summary.json      # 评审、测试摘要
```

### 合并到主项目（可配置）

开启 `MERGE_ENABLED=true` 后，代码会拷贝到：

```text
{MERGE_TARGET_ROOT}/backend/    ← 后端
{MERGE_TARGET_ROOT}/frontend/   ← 前端
```

示例：桌面 `all` 项目

```text
/Users/liyue/Desktop/all/
├── backend/
└── frontend/
```

**说明**：`output/` 保留每次运行快照；主项目目录用于日常开发合并，两者互不影响。

**已存在文件合并不进去？** 多为 `MERGE_CONFLICT_MODE=manual`：新路径会拷贝，内容不同的已存在文件**不会覆盖**，会导出到 `.merge_conflicts/run_xxx/` 下的 `.current` / `.incoming`。解决：设 `MERGE_CONFLICT_MODE=overwrite` 或侧边栏选「覆盖」，或：

```bash
python3 pipeline.py --merge-run output/run_20260522_xxx --merge-mode overwrite -m /Users/liyue/Desktop/all
```

---

## Prompt 与 Skill

| 类型 | 位置 | 作用 |
|------|------|------|
| **Prompt** | `prompts.py` | 各 Agent 的 system / user 模板 |
| **Skill** | `skills/*/SKILL.md` | 工程规范（API 契约、Vue、评审清单等） |

修改 Prompt：编辑 `prompts.py` 中 `_SYSTEM`、`_USER`。

修改规范：编辑 `skills/<名称>/SKILL.md`，无需改 `pipeline.py`。

---

## 侧边栏配置项（Streamlit）

| 配置项 | 说明 |
|--------|------|
| 输出根目录 | 默认 `项目目录/output` |
| 交付后自动合并 | 勾选后拷贝到主项目 |
| 主项目根目录 | 如 `/Users/liyue/Desktop/all` |
| 后端/前端子目录名 | 默认 `backend`、`frontend` |
| 存量项目路径 | 可选，扫描老项目结构与依赖 |

---

## 常见问题

### Mock 模式 vs 真实 API

- 侧边栏显示 **Mock 模式: 关闭** → 使用 `.env` 中的真实 API
- 无 Key 或 `USE_MOCK_LLM=true` → 走本地模板，流程可跑通但代码为演示模板

### 评审得分为 0

已做修复：静态评分与 LLM 评分加权合并，避免模型返回 `0` 覆盖合理分数。若仍异常，查看终端日志中 `CodeReview LLM 原始回复`。

### 合并失败

1. 确认 `MERGE_TARGET_ROOT` 路径存在或可自动创建
2. 确认 `MERGE_ENABLED=true` 或界面已勾选合并
3. 查看日志 `[Deliver] 已合并到主项目` 或失败原因

### 停止服务

在运行 Streamlit 的终端按 `Ctrl + C`。

---

## 安全提示

- `.env` 含 API Key，已加入 `.gitignore`，**勿提交到 Git**
- 密钥泄露后请在云平台轮换

---

## 在 VS Code 中使用

本项目不依赖 Cursor，用 VS Code 打开 `u` 目录即可编辑。启动命令同上：

```bash
python3 -m streamlit run app.py
```

---

## 依赖列表

见 `requirements.txt`：

- langgraph
- langchain-core / langchain-openai
- streamlit
- python-dotenv
