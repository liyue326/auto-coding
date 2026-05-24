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
| `MEMORY_ENABLED` | `true` 开启 Chroma 修复经验库 |
| `CHROMA_PERSIST_DIR` | 向量库目录，默认 `data/chroma` |
| `MEMORY_TOP_K` | BugFix 检索历史案例条数，默认 `3` |
| `EMBEDDING_MODEL` | 嵌入模型，默认 `text-embedding-v3`（DashScope） |

### 多轮对话记忆（LangGraph Checkpoint）

| 变量 | 说明 |
|------|------|
| `LANGGRAPH_CHECKPOINT_ENABLED` | 编译图时挂载 Checkpointer |
| `LANGGRAPH_CHECKPOINT_DB` | SQLite 路径，默认 `data/checkpoints/langgraph.db` |
| `CONVERSATION_MEMORY_ENABLED` | 启用多轮对话记忆 |
| `CONVERSATION_USE_CHECKPOINT` | 从 Checkpoint 读/写 `conversation_turns`（默认 `true`） |
| `CONVERSATION_USE_JSONL` | 是否双写 JSONL（默认 `false`） |
| `CONVERSATION_MAX_TURNS` | 注入 Prompt 的历史轮数 |
| `CONVERSATION_DEFAULT_THREAD` | 默认 `thread_id`（= 侧边栏「对话线程 ID」） |

- 技术：**LangGraph 自带 `SqliteSaver`** + `thread_id`；状态里 `conversation_turns` 列表追加每轮摘要
- 每次新需求：`reset_run` 清空上一轮代码产物，**不**清空对话轮次
- 依赖：`pip install langgraph-checkpoint-sqlite`
- 与 Chroma **修复经验库** 独立

### 修复经验向量库（Chroma）

- **只入库成功修复**：流水线 **测试通过** 且经历过 **BugFix** 时，Deliver 写入**最后一轮**修复记录
- **检索时机**：BugFix 根据当前缺陷 + 需求检索 Top-K 相似案例，注入 Prompt（仅参考手法，不改业务）
- **数据目录**：`data/chroma/`（已加入 `.gitignore`）

```bash
pip install -r requirements.txt
# 通义 DashScope 建议: EMBEDDING_MODEL=text-embedding-v3
```

### 何时进入 BugFix

流水线只有在 **CodeReview 通过 → TestAgent 检出缺陷 → 测试未通过** 时才会进入 BugFix：

```text
评审通过 → 测试 → defects 非空 → BugFix → 再测 → … → 通过 → Deliver（入库经验）
```

常见触发条件：

- 后端路由文件（含 `APIRouter` / `routes.py`）缺少 `HTTPException`
- 前端 `.vue` 含 `password` 但未设置 `type="password"`
- TestAgent LLM 返回的 `defects` 列表非空

**仅前端需求**（如「画圆只要前端」）通常不会进 BugFix，因无后端路由检测项。

日志中应出现：`检出缺陷 N 条` → `路由: 测试失败…进入 BugFix`。

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
PrepareWorkspace（隔离复制老项目，只读快照 + 索引）
    ↓
Project Analyst（结构 / 代码风格 / 可复用组件 → 上下文报告）
    ↓
Supervisor / Planner（任务拆分 + API 契约，必读 Analyst 报告）
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
| PrepareWorkspace | 复制老项目到 `data/workspaces/`，生成 `project_map.json`（不改原目录） |
| Project Analyst | 扫描结构、提取风格、识别可复用组件，输出 `analyst_report.json` |
| Supervisor | 拆分任务、定义 API 契约（消费 Analyst 报告） |
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
