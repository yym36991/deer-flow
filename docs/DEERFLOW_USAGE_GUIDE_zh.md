# DeerFlow 使用指南（HTTP 集成版）

本文面向**平台侧 / 业务系统集成**，说明如何通过 Gateway HTTP API 使用 DeerFlow：创建会话、流式对话、Thread 管理、Skills 与 MCP 工具接入、自定义 Agent、人在回路（HITL）。

> **服务入口**
> - 开发/生产统一入口（Nginx）：`http://127.0.0.1:2026`
> - Gateway 直连（调试）：`http://127.0.0.1:8001`
> - LangGraph 兼容路径：`/api/langgraph/*` 会被 Nginx 重写到 Gateway 原生 `/api/*`

**建议环境变量（下文 curl 均以此为准）：**

```bash
export GATEWAY="http://127.0.0.1:8001"
export INTERNAL_TOKEN="X-DeerFlow-Internal-Token-valid"   # 替换为真实 token
export OWNER="zhangsan"
```

---

## 目录

1. [认证与用户隔离](#一认证与用户隔离)
2. [Thread 生命周期](#二thread-生命周期)
3. [对话接口 `/api/runs/stream`](#三对话接口-apirunsstream)
4. [Skills 接入](#四skills-接入)
5. [MCP 工具接入](#五mcp-工具接入)
6. [自定义 Agent API](#六自定义-agent-api)
7. [人在回路 HITL](#七人在回路-hitl)
8. [附录：其他常用接口与排错](#附录其他常用接口与排错)

---

## 一、认证与用户隔离

DeerFlow 有两套调用方式：

| 场景 | 认证方式 |
|------|----------|
| 浏览器 / 前端 UI | Cookie 会话 + CSRF |
| **平台内部集成（本文重点）** | `X-DeerFlow-Internal-Token` + `X-DeerFlow-Owner-User-Id` |

### 1.1 Internal Token

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `X-DeerFlow-Internal-Token` | 是 | 表示从**受信任的平台**接入；值等于 Gateway 环境变量 `DEER_FLOW_INTERNAL_AUTH_TOKEN`（或部署配置中的对应项）。缺失或错误 → **401** |

### 1.2 用户隔离

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `X-DeerFlow-Owner-User-Id` | 多用户场景必填 | 平台侧用户 ID，如 `zhangsan`。Thread、上传目录、自定义 Agent、Skills 用户态等按该 ID 隔离。数据目录示例：`.deer-flow/users/zhangsan/threads/{thread_id}/...` |

> **注意**：创建 Thread / 发起对话 / 查询列表时，`X-DeerFlow-Owner-User-Id` 必须**保持一致**，否则会出现「库里有记录但 search 查不到」的情况（按不同 `user_id` 过滤）。

---

## 二、Thread 生命周期

Thread 是对话会话单元，对应 LangGraph checkpoint 与 DeerFlow 元数据（`threads_meta` 表 / `thread_meta` 存储）。

### 2.1 两种创建方式

#### 方式 A：显式创建（`POST /api/threads`）

适合：会话列表页、首聊前固定 `thread_id`、预先写入业务 metadata。

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `Content-Type` | 是 | `application/json` |
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 多用户必填 | 如 `zhangsan`，写入 `threads_meta.user_id` |

**请求体**

| 参数 | 必填 | 说明 |
|------|------|------|
| `thread_id` | 否 | 自定义 UUID；省略则由 DeerFlow 自动生成。已存在则**幂等**返回原记录 |
| `assistant_id` | 否 | 关联的 Agent 名称，如 `lead_agent` 或自定义 Agent |
| `metadata` | 否 | 业务元数据，写入 `threads_meta.metadata_json`，可用于 search 过滤 |

**示例 1：`thread_id` 自动生成**

```bash
curl -sS -X POST "${GATEWAY}/api/threads" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{}'
```

响应示例：

```json
{
  "thread_id": "92e95b09-7016-4d5e-94e9-d35d3f9cf2f0",
  "status": "idle",
  "created_at": "2026-07-20T02:27:13.116615+00:00",
  "updated_at": "2026-07-20T02:27:13.116615+00:00",
  "metadata": {},
  "values": {},
  "interrupts": {}
}
```

**示例 2：指定 `thread_id` 与 metadata**

```bash
curl -sS -X POST "${GATEWAY}/api/threads" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{
    "thread_id": "my-thread-001",
    "metadata": {
      "label": "部署助手",
      "source": "ops-platform"
    }
  }'
```

响应示例：

```json
{
  "thread_id": "my-thread-001",
  "status": "idle",
  "created_at": "2026-07-20T02:30:07.265287+00:00",
  "updated_at": "2026-07-20T02:30:07.265287+00:00",
  "metadata": {
    "label": "部署助手",
    "source": "ops-platform"
  },
  "values": {},
  "interrupts": {}
}
```

显式创建还会写入**空 checkpoint**，因此首条消息发送前即可调用 `GET /api/threads/{id}/state`。

#### 方式 B：隐式创建（`POST /api/runs/stream` 首聊）

调用 `POST /api/runs/stream` 且**不传** `config.configurable.thread_id` 时，Gateway 自动分配 `thread_id`，并在响应头返回：

```http
Content-Location: /api/threads/{thread_id}/runs/{run_id}
```

首条 SSE 事件 `metadata` 也会携带 `thread_id`、`run_id`。

> **与 search 的关系**：当前版本在 `start_run()` 时会 upsert `threads_meta` 记录，隐式创建的 Thread **通常也会出现在列表中**。仍建议在需要预置 metadata / 固定 thread_id 时优先用方式 A；upsert 失败时 run 仍会继续（仅 warning），显式创建失败则直接 500。

### 2.2 获取 Thread 列表（`POST /api/threads/search`）

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `Content-Type` | 是 | `application/json` |
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 多用户必填 | 只返回该用户的 Thread（按 `threads_meta.user_id` 过滤） |

**请求体**

| 参数 | 必填 | 说明 |
|------|------|------|
| `limit` | 否 | 每页条数，默认 100，范围 1–1000 |
| `offset` | 否 | 分页偏移，默认 0 |
| `metadata` | 否 | 按 `threads_meta.metadata_json` **精确匹配**过滤（键值全匹配） |
| `status` | 否 | 按 thread 状态过滤，如 `idle`、`running` |

**示例**

```bash
curl -sS -X POST "${GATEWAY}/api/threads/search" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{"limit": 20}'
```

响应为 Thread 数组，按 `updated_at` 降序（最新在前）：

```json
[
  {
    "thread_id": "my-thread-001",
    "status": "idle",
    "created_at": "2026-07-13T09:33:08.886485+00:00",
    "updated_at": "2026-07-13T09:33:08.886485+00:00",
    "metadata": {"label": "部署助手", "source": "ops-platform"},
    "values": {},
    "interrupts": {}
  }
]
```

若 `values.title` 有值，表示 Agent 已自动生成会话标题（`display_name`）。

### 2.3 获取 / 更新 / 删除 Thread

以下接口路径参数 `{thread_id}` 均为必填。

---

#### 2.3.1 获取 Thread 元数据 — `GET /api/threads/{thread_id}`

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 多用户必填 | 须为 Thread 所属用户，否则 404 |

**请求体**：无

**响应字段**

| 字段 | 说明 |
|------|------|
| `thread_id` | Thread ID |
| `status` | 运行状态：`idle` / `running` 等（结合 checkpoint 推导） |
| `created_at` / `updated_at` | ISO 8601 时间 |
| `metadata` | 业务元数据 |
| `values` | 当前 checkpoint 中的 channel values 摘要（含 messages 等，若已有对话） |
| `interrupts` | 中断信息（HITL 等场景） |

**示例**

```bash
curl -sS "${GATEWAY}/api/threads/my-thread-001" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

---

#### 2.3.2 获取 Thread 完整状态 — `GET /api/threads/{thread_id}/state`

用于拉取最新 checkpoint 快照：**完整 messages、artifacts、thread_data** 等。HITL 场景下可用此接口轮询 pending 的 `ask_clarification`（不必只靠 SSE）。

**请求头**：同 2.3.1

**请求体**：无

**响应字段（主要）**

| 字段 | 说明 |
|------|------|
| `values` | 图 channel 值：`messages`、`title`、`thread_data`、`artifacts` 等 |
| `next` | 待执行的节点名列表 |
| `metadata` | checkpoint 元数据 |
| `checkpoint_id` | 当前 checkpoint ID |
| `parent_checkpoint_id` | 父 checkpoint ID |
| `tasks` | 中断中的 task 详情 |

**示例**

```bash
curl -sS "${GATEWAY}/api/threads/my-thread-001/state" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

---

#### 2.3.3 更新 Thread 元数据 — `PATCH /api/threads/{thread_id}`

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `Content-Type` | 是 | `application/json` |
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 多用户必填 | Thread 所属用户 |

**请求体**

| 参数 | 必填 | 说明 |
|------|------|------|
| `metadata` | 是 | 要与现有 metadata **浅合并**的键值对：同名字段**覆盖**为新值，新字段**追加**，未出现在请求体中的旧字段**保留**。不会出现两个同名 key |

**合并示例**

假设 Thread 创建时 metadata 为：

```json
{"label": "部署助手", "source": "ops-platform"}
```

执行下方 PATCH 后，结果为（**只有一个 `label`**）：

```json
{"label": "生产部署", "source": "ops-platform", "priority": "high"}
```

- `label`：`部署助手` → `生产部署`（覆盖，不是新增第二个 label）
- `source`：未出现在 PATCH 中，**保留**
- `priority`：新键，**追加**

**示例**

```bash
curl -sS -X PATCH "${GATEWAY}/api/threads/my-thread-001" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{"metadata": {"label": "生产部署", "priority": "high"}}'
```

---

#### 2.3.4 删除 Thread — `DELETE /api/threads/{thread_id}`

删除 Thread 关联的：本地文件目录、checkpoint、`threads_meta` 行。

**请求头**：同 2.3.1

**请求体**：无

**示例**

```bash
curl -sS -X DELETE "${GATEWAY}/api/threads/my-thread-001" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

响应含删除的文件路径等信息。删除后该 `thread_id` 不再出现在 search 结果中。

---

### 2.4 续聊

在 `POST /api/runs/stream` 请求体中指定已有 Thread：

```json
{
  "config": {
    "configurable": {
      "thread_id": "1f5f39a3-7460-42dd-a466-d8f9c0cd55d1"
    }
  },
  "input": {
    "messages": [{"role": "human", "content": "继续上一话题"}]
  }
}
```

LangGraph 兼容路径等价：`POST /api/langgraph/runs/stream`（经 Nginx 时访问 `:2026`）。

---

## 三、对话接口 `/api/runs/stream`

核心流式对话接口，返回 **SSE（Server-Sent Events）**。

```http
POST /api/runs/stream
Content-Type: application/json
Accept: text/event-stream
```

也支持带 path 的形式：`POST /api/threads/{thread_id}/runs/stream`（thread_id 以 path 为准）。

### 3.1 请求头

| 参数 | 必填 | 说明 |
|------|------|------|
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `Content-Type` | 是 | `application/json` |
| `Accept` | 建议 | `text/event-stream` |
| `X-DeerFlow-Owner-User-Id` | 多用户必填 | 平台用户 ID |
| `Last-Event-ID` | 否 | SSE 断线重连，从该 event id 之后续传 |

### 3.2 请求体

| 参数 | 必填 | 说明 |
|------|------|------|
| `input` | 对话时必填 | 一般为 `{"messages":[{"role":"human","content":"..."}]}`；HITL 回复见第七章 |
| `assistant_id` | 否 | 默认 `lead_agent`；自定义 Agent 填其 `name` |
| `context` | 否 | DeerFlow 扩展运行时上下文，合并到 `config.context`（见 3.3） |
| `config` | 否 | LangGraph RunnableConfig；步数上限、trace 标签、`thread_id` 等 |
| `metadata` | 否 | **写入 runs 表** `metadata_json`，用于业务归档 |
| `multitask_strategy` | 否 | 默认 `reject`；同 thread 有进行中 run 时：`reject` / `interrupt` / `rollback` |
| `stream_mode` | 否 | SSE 事件类型，默认 `values` |
| `stream_subgraphs` | 否 | 默认 `false`；`true` 时包含子 Agent 子图事件 |
| `on_disconnect` | 否 | 默认 `cancel`；`continue` 时客户端断开后台继续跑 |
| `command` | 否 | LangGraph Command；HITL / checkpoint resume 等 |

**当前未实现**：`enqueue`、`webhook`、`after_seconds`、`on_completion`、`if_not_exists`、`feedback_keys`、`stream_resumable`。

**`context` 常用键**（推荐放顶层 `context`，更简单）：

| 键 | 说明 |
|----|------|
| `model_name` | 覆盖模型 |
| `thinking_enabled` | 开启扩展思考 |
| `subagent_enabled` | 开启子 Agent |
| `max_concurrent_subagents` | 并发子 Agent 上限 |
| `max_total_subagents` | 单次 run 子 Agent 总数上限 |
| `is_plan_mode` | 计划模式（TodoList） |
| `is_bootstrap` | 引导流程 |
| `agent_name` | Agent 名称提示 |

### 3.3 `config` 常见子字段

| 子字段 | 说明 |
|--------|------|
| `config.configurable.thread_id` | 指定 Thread，**续聊必填** |
| `config.configurable.checkpoint_ns` | 子 Agent checkpoint 命名空间 |
| `config.context` | 运行时 context；顶层 `context` 会补充未设置的字段 |
| `config.recursion_limit` | 图最大步数，默认 100，服务端有上限 `max_recursion_limit` |
| `config.tags` | LangSmith trace 标签 |
| `config.run_name` | LangSmith trace 名称 |
| `config.metadata` | 主要进 Langfuse/LangSmith trace；顶层 `metadata` 会合并进来 |

**字段选型速查**

| 目的 | 推荐字段 |
|------|----------|
| 换模型、开思考、开子 Agent | 顶层 `context` |
| 限制图步数、打 trace 标签 | `config` |
| 平台业务归档（进 runs 表） | 顶层 `metadata` |
| trace 观测 | `config.metadata` |

### 3.4 示例：无 Thread 首聊

```bash
curl -i -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{"input":{"messages":[{"role":"human","content":"你好,22+22=?"}]}}'
```

响应头含 `Content-Location: /api/threads/{thread_id}/runs/{run_id}`。

SSE 事件序列：

| event | 说明 |
|-------|------|
| `metadata` | `{"run_id":"...","thread_id":"..."}` |
| `values` | 全量状态快照：`messages`、`title`、`thread_data` 等 |
| `end` | 流结束 |

`thread_data` 示例：

```json
{
  "workspace_path": ".../users/zhangsan/threads/{id}/user-data/workspace",
  "uploads_path": ".../uploads",
  "outputs_path": ".../outputs"
}
```

Agent 内虚拟路径：`/mnt/user-data/workspace`、`/mnt/user-data/uploads`、`/mnt/user-data/outputs`。

### 3.5 示例：带 Thread 续聊

```bash
curl -i -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{
    "config": {"configurable": {"thread_id": "1f5f39a3-7460-42dd-a466-d8f9c0cd55d1"}},
    "input": {"messages": [{"role": "human", "content": "你好,33+33=?"}]}
  }'
```

续聊后 `values.messages` 会包含完整历史消息。

### 3.6 其他 stream_mode

| 值 | 说明 |
|----|------|
| `values` | 全量状态快照（默认） |
| `messages-tuple` | 增量消息 |
| `updates` | 图状态更新时推送（调试用，可看节点名） |
| `custom` | 自定义事件（如 subagent 进度） |

### 3.7 同步等待 — `POST /api/runs/wait`

请求体与 `/api/runs/stream` 相同，阻塞至 run 结束，一次性返回最终状态（适合短任务脚本，不适合长对话）。

---

## 四、Skills 接入

Skills 是给 Agent 的**领域能力包**（Markdown 指令 + 可选脚本/资源）。Agent 在对话中通过内置工具按需加载 `SKILL.md`，无需用户在每条消息里手动指定 Skill 名称。

本章分三部分说明：

1. **管理员 / 运维**：如何为全站用户启用、发布 **public Skill**
2. **终端用户**（使用你们部署的 DeerFlow 服务的业务用户）：如何**使用**和**创建**自己的 **custom Skill**
3. **平台 HTTP 集成**（Internal Token）：业务系统能调哪些 Skill 相关 API

---

### 4.1 两类 Skill 与存储位置

| 类型 | 存放位置 | 谁维护 | 启用开关存在哪 | 作用范围 |
|------|----------|--------|----------------|----------|
| **public** | `skills/public/{name}/` | 管理员 / 运维（随部署或 Git） | 全局 `extensions_config.json` | **所有用户**共享同一套开关 |
| **custom** | `.deer-flow/users/{user_id}/skills/custom/{name}/` | 终端用户（或 Agent 代写） | 用户级 `_skill_states.json` | **仅该用户**可见、可编辑 |

Legacy 说明：旧版全局 `skills/custom/` 目录中的 Skill 会以 **LEGACY** 只读形式展示；用户一旦创建了自己的 custom Skill，Legacy 列表对该用户不再出现。

**Skill 包最小结构：**

```
my-skill/
├── SKILL.md          # 必需：YAML frontmatter + 指令正文
├── scripts/          # 可选
└── references/       # 可选
```

`SKILL.md` frontmatter 示例：

```yaml
---
name: deep-research
description: 需要系统性网络调研时使用。用户问「什么是 X」「调研 X」时触发。
---
# Deep Research Skill
（正文：步骤、约束、示例）
```

- `name` 与目录名一致
- `description` 决定 Agent **何时加载**，务必写清触发条件

---

### 4.2 角色与权限（先看这张表）

| 能力 | 管理员（`system_role=admin`，浏览器登录） | 终端用户（普通登录用户） | 平台 Internal Token（如 `zhangsan`） |
|------|------------------------------------------|--------------------------|--------------------------------------|
| 查看 Skill 列表 | ✅ `GET /api/skills` | ✅ 设置页 + API | ✅ `GET /api/skills`（带 Owner 头） |
| 启用/禁用 **public** Skill | ✅ UI 开关 / `PUT /api/skills/{name}` | ❌ UI 开关灰色不可用 | ❌ 403，需改配置文件或找管理员 |
| 启用/禁用 **custom** Skill | ✅ | ❌（API 同样要求 admin） | ❌ |
| 安装 `.skill` 包 | ✅ `POST /api/skills/install` | ❌ | ❌ |
| 刷新 Skill 缓存 | ✅ `POST /api/skills/reload` | ❌ | ❌ |
| 编辑/删除 custom Skill（HTTP） | ✅ `/api/skills/custom/*` | ❌ | ❌ |
| **对话中使用**已启用的 Skill | ✅ 自动 | ✅ 自动 | ✅ 自动（run 时 Agent 加载） |
| **创建 custom Skill**（对话 + Agent） | ✅ 需 `skill_evolution.enabled` | ✅ 同上 | ✅ 以 Owner 用户身份对话时可创建 |
| 直接改 `extensions_config.json` | ✅ 运维 | ❌ | ❌（改服务器文件，非 API） |

> **重要**：`X-DeerFlow-Owner-User-Id: zhangsan` 只表示「以 zhangsan 的身份读写数据」，**不等于 admin**。admin 是 DeerFlow 账号体系里的管理员角色，与 Owner 头无关。

---

### 4.3 管理员：public Skill 运维

#### 4.3.1 启用 / 禁用 public Skill

**方式 A（推荐生产）：改配置文件 + 重启 Gateway**

编辑服务器上的 `extensions_config.json`：

```json
{
  "mcpServers": { },
  "skills": {
    "deep-research": {"enabled": true},
    "frontend-design": {"enabled": false}
  }
}
```

保存后**重启 Gateway**（或滚动重启 Pod）。无需调 reload API。

**方式 B：Admin 账号调 API**

浏览器以 **admin** 登录 DeerFlow，带 Cookie + CSRF：

```bash
curl -sS -X PUT "${GATEWAY}/api/skills/deep-research" \
  -H "Content-Type: application/json" \
  -H "Cookie: <admin_session_cookie>" \
  -H "X-CSRF-Token: <csrf_token>" \
  -d '{"enabled": true}'
```

刷新缓存（可选，改磁盘上的 custom/public 文件后）：

```bash
curl -sS -X POST "${GATEWAY}/api/skills/reload" \
  -H "Cookie: <admin_session_cookie>" \
  -H "X-CSRF-Token: <csrf_token>"
```

#### 4.3.2 发布新的 public Skill

1. 在部署包的 `skills/public/{name}/` 下添加 Skill 目录（含 `SKILL.md`）
2. 在 `extensions_config.json` 的 `skills` 块增加 `"name": {"enabled": true}`
3. 重启 Gateway
4. `GET /api/skills` 确认出现且 `enabled: true`

public Skill **不应**通过终端用户对话创建；应走发版 / 运维流程。

#### 4.3.3 前置配置：允许用户创建 custom Skill

若希望终端用户（或 Agent）能**创建** custom Skill，需在 `config.yaml` 开启：

```yaml
skill_evolution:
  enabled: true
  moderation_model_name: null   # Skill 安全扫描用的模型，null 用默认模型
```

开启后，Lead Agent 会获得 `skill_manage` 工具，可将 Skill 写入用户目录 `.deer-flow/users/{user_id}/skills/custom/`。默认 `enabled: false` 时用户只能**使用**已有 Skill，不能通过 Agent 新建。

---

### 4.4 终端用户：如何使用 Skill

终端用户**不需要**在每条消息里写「请加载 deep-research」。流程如下：

1. **管理员**已在 `extensions_config.json` 启用需要的 public Skill（如 `deep-research`）
2. 用户在 DeerFlow **Web 聊天**或你们平台嵌入的对话框里正常提问
3. Agent 根据各 Skill 的 `description` 与当前任务，自动决定是否调用 `load_skill` / 遵循 Skill 指令
4. 用户可在 **设置 → Skills** 查看 public / custom 列表与说明（启用开关仅 admin 可操作）

**使用 custom Skill：**

- 用户通过下文 4.5 创建 custom Skill 后，**默认即为启用**（除非被全局或用户级状态关闭）
- custom Skill **仅创建者**（对应 `user_id`）在对话中可见、可加载

**在自定义 Agent 中限定 Skill 白名单**（平台 API，见第六章）：

```json
{
  "name": "my-agent",
  "skills": ["deep-research"],
  "tool_groups": ["web"]
}
```

`skills: []` 表示该 Agent 不使用任何 Skill；省略或 `null` 表示使用当前用户所有已启用的 Skill。

---

### 4.5 终端用户：如何创建 custom Skill

有三种常见路径，按推荐顺序：

#### 方式 1：Web UI「创建 Skill」引导（推荐）

1. 登录 DeerFlow → **设置 → Skills**
2. 点击 **「创建 Skill」**（进入 `/workspace/chats/new?mode=skill`）
3. 在对话中描述需求，Agent 会使用内置 **skill-creator** 流程引导：定目标 → 写 `SKILL.md` 草稿 → 试跑 → 迭代
4. 前提：`skill_evolution.enabled: true`，Agent 才能调用 `skill_manage` 持久化文件

**不要**用普通 `write_file` 把 `SKILL.md` 写到 `/mnt/user-data/outputs/`——那样只对当前 Thread 可见，其他会话加载不到。必须通过 **`skill_manage`**（Agent 自动调用）写入用户 Skill 目录。

`skill_manage` 常用动作：

| action | 用途 |
|--------|------|
| `create` | 新建 Skill，传入完整 `SKILL.md` 内容 |
| `edit` | 整文件替换 |
| `patch` | 局部 find/replace |
| `write_file` | 添加 `scripts/`、`references/` 等附属文件 |
| `delete` | 删除整个 custom Skill |

创建成功后 Skill 立即可用于该用户**后续所有新对话**（同 `user_id`）。

#### 方式 2：平台 API 代用户对话创建

你们的业务系统用 Internal Token + `X-DeerFlow-Owner-User-Id: zhangsan` 发起对话，消息示例：

```json
{
  "input": {
    "messages": [{
      "role": "human",
      "content": "帮我创建一个 Skill：名称 order-review，用于审查订单数据是否符合公司规范……"
    }]
  },
  "context": { "is_bootstrap": false }
}
```

同样需要服务端 `skill_evolution.enabled: true`。Agent 创建结果落在 `.deer-flow/users/zhangsan/skills/custom/order-review/`。

#### 方式 3：Admin 安装 `.skill` 包

1. 用户将 `.skill` 文件上传到某 Thread（`POST /api/threads/{id}/uploads`）
2. **Admin** 调用：

```json
POST /api/skills/install
{
  "thread_id": "<thread_id>",
  "path": "/mnt/user-data/uploads/my-skill.skill"
}
```

安装到对应用户的 custom 目录（需 admin 权限）。适合运维统一分发，不适合普通终端用户自助。

#### 方式 4：运维直接落盘（高级）

将 Skill 目录复制到：

```text
.deer-flow/users/{user_id}/skills/custom/{skill_name}/SKILL.md
```

重启 Gateway 或 admin 执行 `POST /api/skills/reload`。适合批量迁移，一般不开放给业务用户。

---

### 4.6 HTTP 管理接口（按角色）

#### 4.6.1 列出所有 Skill — `GET /api/skills`

**权限**：Internal Token ✅｜终端用户 Cookie ✅｜Admin ✅

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `X-DeerFlow-Internal-Token` | Internal 调用时必填 | |
| `X-DeerFlow-Owner-User-Id` | 建议 | 决定 custom / LEGACY Skill 的用户视图 |

```bash
curl -sS "${GATEWAY}/api/skills" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

响应示例：

```json
{
  "skills": [
    {
      "name": "deep-research",
      "display_name": "Deep Research",
      "description": "...",
      "enabled": true,
      "license": "MIT",
      "path": "public/deep-research",
      "category": "public"
    },
    {
      "name": "order-review",
      "description": "...",
      "enabled": true,
      "path": "custom/order-review",
      "category": "custom"
    }
  ]
}
```

#### 4.6.2 获取 Skill 详情 — `GET /api/skills/{skill_name}`

**权限**：同上（只读）

```bash
curl -sS "${GATEWAY}/api/skills/deep-research" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

#### 4.6.3 启用 / 禁用 — `PUT /api/skills/{skill_name}`

**权限：仅 admin**（Internal Token / 普通用户 → **403**）

| 请求体字段 | 必填 | 说明 |
|------------|------|------|
| `enabled` | 是 | `true` / `false` |

- **public**：写全局 `extensions_config.json`，影响所有用户
- **custom**：写该用户目录下 `_skill_states.json`（admin 代操作时作用于 admin 登录用户，非 Owner 头用户）

#### 4.6.4 安装 `.skill` 包 — `POST /api/skills/install`

**权限：仅 admin**

| 请求体字段 | 必填 | 说明 |
|------------|------|------|
| `thread_id` | 是 | 含 `.skill` 文件的 Thread |
| `path` | 是 | 虚拟路径，如 `/mnt/user-data/uploads/foo.skill` |

#### 4.6.5 刷新缓存 — `POST /api/skills/reload`

**权限：仅 admin**。进程内失效 Skill 提示词缓存；**不会**重新读取 `extensions_config.json`（改 public 开关仍需重启或走 PUT）。

#### 4.6.6 Custom Skill 编辑 API — `/api/skills/custom/*`

**权限：仅 admin**（供管理后台或运维脚本；终端用户应走对话 + `skill_manage`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills/custom` | 列出当前用户的 custom Skill（无需 admin） |
| GET | `/api/skills/custom/{name}` | 读取 `SKILL.md` 全文 |
| PUT | `/api/skills/custom/{name}` | 编辑内容（安全扫描） |
| DELETE | `/api/skills/custom/{name}` | 删除 |
| GET | `/api/skills/custom/{name}/history` | 变更历史 |
| POST | `/api/skills/custom/{name}/rollback` | 回滚 |

---

### 4.7 场景速查

| 场景 | 谁来做 | 怎么做 |
|------|--------|--------|
| 全站开放「深度调研」能力 | 管理员 | `extensions_config.json` 启用 `deep-research` + 重启 |
| 业务用户自建「订单审查」Skill | 终端用户 | UI「创建 Skill」或平台代发对话；需 `skill_evolution.enabled` |
| 平台查询 zhangsan 有哪些 Skill | 平台集成 | `GET /api/skills` + Owner=`zhangsan` |
| 平台帮用户开/关 public Skill | 管理员 | 改配置或 admin PUT；**不能**用 Internal Token 代替 |
| 对话中自动用 Skill | 终端用户 / 平台 | 正常 `POST /api/runs/stream`，无需额外字段 |
| 限制某 Agent 只用部分 Skill | 平台 | 创建 Agent 时设 `skills: ["deep-research"]` |

### 4.8 注意事项

1. public Skill 开关是**全局**的；终端用户不能自行打开未启用的 public Skill
2. custom Skill **默认创建即启用**；关闭需 admin 调 API 或写 `_skill_states.json`
3. 不要在 Skill 里重复实现 DeerFlow 内置文件工具（`read_file` / `write_file` 等）已覆盖的能力
4. 创建 / 编辑 Skill 会经过安全扫描（SkillScan）；含恶意指令的可能被 block
5. 改 `extensions_config.json` 后**重启 Gateway**；`/api/skills/reload` 只刷新缓存，不替代重启

---

## 五、MCP 工具接入

MCP（Model Context Protocol）用于挂载外部工具服务：GitHub、PostgreSQL、企业内部 HTTP API 等。配置后 Agent 自动发现 MCP 工具（工具名带 `{server}_` 前缀，如 `github_create_issue`）。

### 5.1 配置文件

根目录 `extensions_config.json` → `mcpServers`：

```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
      "tool_call_timeout": 60,
      "description": "GitHub 仓库操作"
    },
    "postgres": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"],
      "routing": {
        "mode": "prefer",
        "priority": 50,
        "keywords": ["数据库", "SQL", "订单", "用户"]
      }
    }
  },
  "skills": {}
}
```

环境变量用 `$VAR` 引用，**不要**在配置文件中明文写密钥。

### 5.2 传输类型

| type | 说明 | 备注 |
|------|------|------|
| `stdio` | 本地子进程 | 常用 `npx`、`uvx`；支持 `tool_call_timeout`（秒） |
| `sse` | 远程 SSE MCP | 使用传输层超时 |
| `http` | 远程 HTTP MCP | 支持 OAuth（`oauth` 配置块） |

`command` 默认只允许 `npx`、`uvx`；可通过环境变量 `DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST` 扩展白名单。

### 5.3 路由提示 routing（可选）

软引导模型优先选用某 MCP 工具（**不禁止**其他工具）：

```json
"routing": {
  "mode": "prefer",
  "priority": 50,
  "keywords": ["查库", "订单表"]
}
```

- `mode: "prefer"` 才生效；`off` 关闭
- `priority` 0–100，越高越优先展示
- `keywords` 与最新用户消息做子串匹配（区分度要高，避免误匹配）

### 5.4 HTTP 管理接口

> 以下接口需要 **admin 用户**（Cookie + CSRF）。平台集成推荐直接维护 `extensions_config.json` + 重启 / cache reset。

#### 5.4.1 查看配置 — `GET /api/mcp/config`

返回当前 MCP 配置，**密钥字段脱敏**（显示 `***`）。

#### 5.4.2 更新配置 — `PUT /api/mcp/config`

**请求体**

```json
{
  "mcp_servers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}
    }
  }
}
```

写入 `extensions_config.json` 并热重载。已有 `$VAR` 占位符会被保留。

#### 5.4.3 重置工具缓存 — `POST /api/mcp/cache/reset`

清空当前 Gateway 进程内 MCP 工具缓存与会话池，下次 run 重新加载。

### 5.5 接入步骤（业务方 checklist）

1. `cp extensions_config.example.json extensions_config.json`
2. 在 `mcpServers` 添加 server 块，`"enabled": true`
3. 在 Gateway 运行环境配置所需环境变量（如 `GITHUB_TOKEN`）
4. 重启 Gateway，或 `POST /api/mcp/cache/reset`
5. 发起对话，在 SSE / Langfuse trace 中确认 Agent 调用了 `{server}_*` 工具

### 5.6 注意事项

- **不要**为 DeerFlow workspace 再挂 MCP filesystem 服务器 — 与内置 `read_file` / `write_file` 路径语义冲突
- OAuth 配置见 [backend/docs/MCP_SERVER.md](../backend/docs/MCP_SERVER.md)
- 自定义拦截器：顶层 `mcpInterceptors` 数组，用于注入 per-request 头等

---

## 六、自定义 Agent API

自定义 Agent 允许为不同业务场景配置独立的 **SOUL.md**（人格/边界）、模型、工具组、Skill 白名单。

**前置条件**：在 `config.yaml` 启用：

```yaml
agents_api:
  enabled: true
```

存储路径：`.deer-flow/users/{user_id}/agents/{name}/`（`SOUL.md` + `config.yaml`）。

所有 Agent API 均需 Internal Token；`X-DeerFlow-Owner-User-Id` 决定 Agent 归属用户。

### 6.1 创建 Agent — `POST /api/agents`

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `Content-Type` | 是 | `application/json` |
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 多用户必填 | Agent 所属用户 |

**请求体**

| 参数 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Agent 名称，仅允许 `^[A-Za-z0-9-]+$`，存储为小写 |
| `description` | 否 | 描述 |
| `model` | 否 | 模型名，须在 `config.yaml` 模型白名单中 |
| `tool_groups` | 否 | 工具组白名单，如 `["web", "file:read"]`；见 `config.yaml` 的 `tool_groups` |
| `skills` | 否 | Skill 白名单；`null`=全部已启用 Skill，`[]`=不用 Skill |
| `soul` | 否 | SOUL.md 正文（Markdown） |

**示例**

```bash
curl -sS -X POST "${GATEWAY}/api/agents" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d @scripts/verify-api/create-custom-agent.json
```

`create-custom-agent.json` 示例：

```json
{
  "name": "zhangsan-agent",
  "description": "张三的技术顾问：简洁、准确、偏工程实践",
  "model": "chatling-plus",
  "tool_groups": ["web", "file:read"],
  "skills": [],
  "soul": "# SOUL.md\n\n你是用户 zhangsan 的专属技术顾问。\n\n## 性格\n- 回答简洁、结构化\n\n## 边界\n- 不编造不存在的 API\n"
}
```

成功返回 **201**，响应含完整 Agent 信息及 `soul` 内容。

**常见错误**

| HTTP | 原因 |
|------|------|
| 403 | `agents_api.enabled` 未开启 |
| 409 | 同名 Agent 已存在 |
| 422 | `name` 格式非法 |

### 6.2 列出 Agent — `GET /api/agents`

**请求头**：Internal Token + Owner

```bash
curl -sS "${GATEWAY}/api/agents" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

### 6.3 获取单个 Agent — `GET /api/agents/{name}`

```bash
curl -sS "${GATEWAY}/api/agents/zhangsan-agent" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

### 6.4 检查名称是否可用 — `GET /api/agents/check?name={name}`

```bash
curl -sS "${GATEWAY}/api/agents/check?name=my-new-agent" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

响应：`{"available": true, "name": "my-new-agent"}`

### 6.5 更新 Agent — `PUT /api/agents/{name}`

**请求体**（均为可选，只更新提供的字段）：

| 参数 | 说明 |
|------|------|
| `description` | 描述 |
| `model` | 模型 |
| `tool_groups` | 工具组 |
| `skills` | Skill 白名单 |
| `soul` | SOUL.md 正文 |

### 6.6 删除 Agent — `DELETE /api/agents/{name}`

```bash
curl -sS -X DELETE "${GATEWAY}/api/agents/zhangsan-agent" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

成功返回 **204**。若遇 307 重定向，加 `-L` 且 URL **不要** trailing slash。

### 6.7 使用自定义 Agent 对话

在 `POST /api/runs/stream` 中指定 `assistant_id`：

```bash
curl -i -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{
    "assistant_id": "zhangsan-agent",
    "input": {"messages": [{"role": "human", "content": "你好"}]}
  }'
```

**常用 tool_groups 值**（以部署 `config.yaml` 为准）：`web`、`file:read`、`file:write`、`bash`。

---

## 七、人在回路 HITL

当 Agent 调用内置工具 `ask_clarification` 时，run 会暂停等待用户输入。业务系统需：

1. 从 SSE（或 `GET .../state`）解析 pending 问题
2. 收集用户答案
3. 再发 `POST /api/runs/stream`，在消息中携带 `human_input_response`

### 7.1 识别待回复问题

在 `event: values` 的 `messages` 末尾查找：

- `type: "tool"`
- `name: "ask_clarification"`
- `artifact.human_input.kind: "human_input_request"`

示例片段：

```json
{
  "type": "tool",
  "name": "ask_clarification",
  "id": "clarification:call_oDHaT50QQdGcBeuQ_MtcZQ",
  "tool_call_id": "call_oDHaT50QQdGcBeuQ_MtcZQ",
  "artifact": {
    "human_input": {
      "version": 1,
      "kind": "human_input_request",
      "source": "ask_clarification",
      "request_id": "clarification:call_oDHaT50QQdGcBeuQ_MtcZQ",
      "question": "您使用的是哪种服务器？",
      "input_mode": "choice_with_other",
      "options": [
        {"id": "option-1", "label": "Linux", "value": "Linux"},
        {"id": "option-2", "label": "Windows", "value": "Windows"},
        {"id": "option-3", "label": "其他", "value": "其他"}
      ]
    }
  }
}
```

**必须保存 `request_id`**（格式 `clarification:{tool_call_id}`）。Agent 重新提问时会生成新的 `tool_call_id`，旧 ID 失效。

### 7.2 回复请求格式

**请求头**：同对话接口

**请求体要点**

| 字段 | 必填 | 说明 |
|------|------|------|
| `config.configurable.thread_id` | 是 | 原 Thread ID |
| `input.messages[0].role` | 是 | `human` |
| `input.messages[0].content` | 是 | 用户答案文本；**须与下方 value 语义一致** |
| `input.messages[0].additional_kwargs.human_input_response` | 是 | 结构化回复，见下表 |

**`human_input_response` 字段**

| 字段 | 必填 | 说明 |
|------|------|------|
| `version` | 是 | 固定 `1` |
| `kind` | 是 | 固定 `"human_input_response"` |
| `source` | 是 | 固定 `"ask_clarification"` |
| `request_id` | 是 | 来自 7.1，必须是**当前 pending** 问题的 ID |
| `response_kind` | 是 | `"option"`（选择题）或 `"text"`（自由文本） |
| `option_id` | 选择题必填 | 如 `option-2`，对应 SSE 中 options 顺序 |
| `value` | 是 | 选项值或自由文本 |

**选择题回复示例**（选「测试环境」）：

```bash
curl -i -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d @scripts/verify-api/hitl-step2-reply.json
```

`hitl-step2-reply.json` 核心结构：

```json
{
  "input": {
    "messages": [{
      "role": "human",
      "content": "测试环境",
      "additional_kwargs": {
        "hide_from_ui": true,
        "human_input_response": {
          "version": 1,
          "kind": "human_input_response",
          "source": "ask_clarification",
          "request_id": "clarification:call_0NRv_L1mQTyYdfwEa2ItpQ",
          "response_kind": "option",
          "option_id": "option-2",
          "value": "测试环境"
        }
      }
    }]
  },
  "config": {"configurable": {"thread_id": "hitl-api-test-002"}}
}
```

**自由文本回复**（无需 `option_id`）：

```json
"response_kind": "text",
"value": "我们用的是 Kubernetes 集群"
```

### 7.3 多轮 HITL 流程

典型部署确认场景（3 步）：

```
Step1  用户发任务 → Agent ask_clarification（目标环境）
Step2  用户选「测试环境」→ Agent ask_clarification（服务器类型）
Step3  用户选「Windows」→ Agent 继续执行或再次 clarify（部署方式）
```

每一步都要从**最新** SSE 取新的 `request_id`。

### 7.4 关键注意事项（必读）

| # | 规则 |
|---|------|
| 1 | **`content` 与 `value` 必须一致**。LLM 主要读 `content`；若 content 写「测试环境」而 value 写「Windows」，会导致 Agent 行为异常 |
| 2 | **`request_id` 必须对应当前 pending 问题**，不能用历史轮次 ID |
| 3 | `option_id` 按 SSE 中 options 顺序（`option-1`、`option-2`…）；后端不校验 option_id 与 value 是否匹配，集成层自行保证 |
| 4 | 可简写 `content` 为纯答案（如 `"Windows"`），不必重复完整问句 |
| 5 | 建议 JSON 放文件用 `-d @file.json`，避免 shell 多行转义问题 |

### 7.5 验证脚本

仓库内可复现：

```bash
# 需先 export GATEWAY / INTERNAL_TOKEN / OWNER
bash scripts/verify-api/test-human-in-the-loop.sh
```

相关 JSON：`scripts/verify-api/hitl-step1-ask.json`、`hitl-step2-reply.json`、`hitl-step3-reply.json`。

---

## 附录：其他常用接口与排错

### A.1 推荐集成流程

```
1. 配置 INTERNAL_TOKEN、OWNER（全程保持一致）
2. POST /api/threads（可选：预置 thread_id / metadata）
3. POST /api/runs/stream → 解析 SSE metadata，持久化 thread_id
4. 循环：用户消息 → runs/stream（带 thread_id）
5. 遇 ask_clarification → 解析 request_id → 构造 human_input_response → 再 stream
6. 需要文件 → POST /api/threads/{id}/uploads → 消息中引用 /mnt/user-data/uploads/...
7. 需要专属 Agent → POST /api/agents → assistant_id 指向该 Agent
```

### A.2 其他 HTTP 接口速查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/models` | 可用模型列表 |
| POST | `/api/threads/{id}/uploads` | 上传文件（multipart `files`） |
| GET | `/api/threads/{id}/uploads/list` | 列出已上传文件 |
| POST | `/api/threads/{id}/runs/{run_id}/cancel` | 取消进行中的 run |
| POST | `/api/runs/wait` | 同步等待 run 结束 |

LangGraph 兼容别名（经 Nginx `:2026`）：

| 兼容路径 | 原生路径 |
|----------|----------|
| `POST /api/langgraph/runs/stream` | `POST /api/runs/stream` |
| `POST /api/langgraph/threads` | `POST /api/threads` |
| `GET /api/langgraph/threads/{id}/state` | `GET /api/threads/{id}/state` |

### A.3 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 401 | Token 错误或缺失 |
| 404 Thread | Owner 头与创建时不一致；或 thread_id 错误 |
| 409 同 thread 第二个 run | 默认 `multitask_strategy: reject`；等待上一个结束或设 `interrupt` |
| HITL 回复后重复提问 | `request_id` 过期，或 `content`/`value` 不一致 |
| search 查不到 Thread | Owner 头不一致；或 metadata 过滤条件不匹配 |
| Agent API 403 | `agents_api.enabled: false` |
| curl JSON 报错 | 使用 `-d @file.json` |

### A.4 延伸阅读

- [backend/docs/API.md](../backend/docs/API.md) — 完整 API 参考
- [backend/docs/MCP_SERVER.md](../backend/docs/MCP_SERVER.md) — MCP 详细配置
- [Install.md](../Install.md) — 安装与启动

---

*文档版本：2026-07。接口以 Gateway 源码为准，升级后请以 `backend/docs/API.md` 核对。*
