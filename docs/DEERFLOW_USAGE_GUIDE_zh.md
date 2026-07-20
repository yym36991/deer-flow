# DeerFlow 使用指南（HTTP 集成版）

本文面向**平台侧 HTTP 集成**：集成平台通过 Internal Token **代各 Owner 用户**（如 `zhangsan`）调用 DeerFlow Gateway API。**无**独立业务后台或 DeerFlow Web UI；End User 即 `X-DeerFlow-Owner-User-Id`。

> **本文部署前提（当前环境）**
> - **仅**使用 `X-DeerFlow-Internal-Token` + `X-DeerFlow-Owner-User-Id` 接入，**不使用** DeerFlow 前端页面
> - **无**浏览器登录的普通用户；「用户」= 平台传入的 Owner ID（如 `zhangsan`、`lisi`）
> - **运维侧**改服务器上的 `config.yaml`、`extensions_config.json` 等配置文件；**集成平台**只调 HTTP API，End User 由 **`Owner` 请求头**标识

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

本部署**只使用 Internal Token**。下文「用户」均指 `X-DeerFlow-Owner-User-Id` 标识的业务身份（如 `zhangsan`），由**你们的平台**在每次请求中传入。

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `X-DeerFlow-Internal-Token` | 是 | 平台信任凭证；值等于 `DEER_FLOW_INTERNAL_AUTH_TOKEN`。错/缺 → **401** |
| `X-DeerFlow-Owner-User-Id` | 是 | 业务用户 ID；Thread、Skill、Agent、上传目录等按此隔离 |

数据目录：`.deer-flow/users/{Owner}/...`

> **注意**：同一业务用户的所有 API 调用必须使用**相同**的 Owner；否则 Thread search、Skill 列表等会对不齐。

**环境变量（curl 示例）：** 见文首 `GATEWAY` / `INTERNAL_TOKEN` / `OWNER`。

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
| `X-DeerFlow-Owner-User-Id` | 是 | 如 `zhangsan`，写入 `threads_meta.user_id` |

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
| `X-DeerFlow-Owner-User-Id` | 是 | 只返回该用户的 Thread（按 `threads_meta.user_id` 过滤） |

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
| `X-DeerFlow-Owner-User-Id` | 是 | 须为 Thread 所属用户，否则 404 |

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
| `X-DeerFlow-Owner-User-Id` | 是 | Thread 所属用户 |

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
| `X-DeerFlow-Owner-User-Id` | 是 | 平台用户 ID |
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

Skills 是 Agent 的**领域能力包**（Markdown + 可选脚本）。对话中 Agent 按 `SKILL.md` 的 `description` **自动**决定是否加载，**无需**在 `input.messages` 里写 Skill 名称。

本章区分两类操作主体：

| 主体 | 是谁 | 典型操作 |
|------|------|----------|
| **运维** | 部署 DeerFlow 的团队 | 启用 public Skill、改 `config.yaml` / `extensions_config.json`、发版 `skills/public/` |
| **平台（业务 API）** | 你们的后端，带 Internal Token + Owner | 查 Skill 列表、代用户对话、代用户创建 custom Skill |

---

### 4.1 两类 Skill

| 类型 | 路径 | 谁维护 | 开关 | 可见范围 |
|------|------|--------|------|----------|
| **public** | `skills/public/{name}/` | 运维（Git / 发版） | 全局 `extensions_config.json` | 所有 Owner 共享 |
| **custom** | `.deer-flow/users/{Owner}/skills/custom/{name}/` | 平台代用户对话创建，或运维落盘 | `{Owner}` 目录下 `_skill_states.json` | **仅该 Owner** |

**Skill 包结构：**

```
{name}/
├── SKILL.md       # 必需（YAML frontmatter + 正文）
├── scripts/       # 可选
└── references/    # 可选
```

```yaml
---
name: deep-research
description: 需要系统性网络调研时使用。用户问「调研 X」时触发。
---
# 正文：步骤与约束
```

---

### 4.2 平台 API 能做什么（Internal Token）

| 能力 | 平台 API（Owner=`zhangsan`） | 说明 |
|------|------------------------------|------|
| 查看 Skill 列表 | ✅ `GET /api/skills` | 含 public + 该 Owner 的 custom |
| 查看 Skill 详情 | ✅ `GET /api/skills/{name}` | 只读 |
| 列出 custom Skill | ✅ `GET /api/skills/custom` | 仅 custom 类别 |
| 对话中**使用**已启用 Skill | ✅ `POST /api/runs/stream` | 正常发消息即可 |
| **创建** custom Skill | ✅ 对话 + Agent `skill_manage` | 需 `skill_evolution.enabled: true` |
| 启用/禁用 public Skill | ❌ | 运维改 `extensions_config.json` + 重启 |
| 启用/禁用 custom Skill | ❌ HTTP 写接口需 DeerFlow admin 角色 | 运维可写 `_skill_states.json`，或暂不关闭 |
| `PUT /api/skills/*`、`install`、`reload` | ❌ | 同上，本部署不走这些 API |

> Gateway 里部分 Skill 写接口校验的是 DeerFlow **admin 账号角色**，与 Internal Token / Owner **无关**。当前部署**不开放前端 admin**，public Skill 开关一律由**运维改配置文件**完成。

---

### 4.3 运维：public Skill

**启用 / 禁用** — 编辑服务器 `extensions_config.json` 后**重启 Gateway**：

```json
{
  "mcpServers": { },
  "skills": {
    "deep-research": {"enabled": true},
    "frontend-design": {"enabled": false}
  }
}
```

**发布新 public Skill：**

1. 在 `skills/public/{name}/` 增加目录与 `SKILL.md`
2. 在上面的 `skills` 块添加 `"name": {"enabled": true}`
3. 重启 Gateway
4. 平台侧验证：`GET /api/skills`（任意 Owner 均可，public 部分一致）

**允许平台代用户创建 custom Skill** — `config.yaml`：

```yaml
skill_evolution:
  enabled: true
  moderation_model_name: null
```

开启后，Lead Agent 具备 `skill_manage` 工具，可将 Skill 写入 `.deer-flow/users/{Owner}/skills/custom/`。未开启时只能**使用**已有 Skill，不能通过对话新建。

---

### 4.4 平台：代用户使用 Skill

流程：

1. 运维已在 `extensions_config.json` 启用所需 public Skill（如 `deep-research`）
2. 平台对某 Owner 调用 `POST /api/runs/stream`，`input.messages` 为正常业务问题
3. Agent 根据 Skill 的 `description` 自动加载并执行

**查询某 Owner 可用 Skill：**

```bash
curl -sS "${GATEWAY}/api/skills" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: zhangsan"
```

响应中 `enabled: true` 的 Skill 才会在对话中参与加载。custom Skill 创建后**默认启用**。

**限定 Agent 只用部分 Skill**（见第六章）：

```json
{
  "assistant_id": "zhangsan-agent",
  "skills": ["deep-research"]
}
```

---

### 4.5 平台：代用户创建 custom Skill

**推荐：对话 + `skill_manage`（需 `skill_evolution.enabled: true`）**

```bash
curl -i -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: zhangsan" \
  -d '{
    "input": {
      "messages": [{
        "role": "human",
        "content": "帮我创建一个 Skill：名称 order-review，用于审查订单数据是否符合公司规范。请写入 SKILL.md 并保存。"
      }]
    }
  }'
```

成功后文件位于：`.deer-flow/users/zhangsan/skills/custom/order-review/SKILL.md`，对该 Owner **后续所有 Thread** 生效。

**注意：**

- 必须靠 Agent 的 **`skill_manage`** 写入用户 Skill 目录；不要用 `write_file` 写到 `/mnt/user-data/outputs/`（仅当前 Thread 可见）
- 创建过程会经过 SkillScan 安全扫描

**备选：运维直接落盘**

```text
.deer-flow/users/zhangsan/skills/custom/{name}/SKILL.md
```

复制完成后重启 Gateway（或联系运维刷新 Skill 缓存）。适合批量迁移，非 API 路径。

---

### 4.6 分发 `.skill` 压缩包（平台上传 + 运维安装）

`.skill` 文件本质是 **ZIP 压缩包**，根目录下应有一个 Skill 文件夹，且包含带 YAML frontmatter 的 `SKILL.md`。安装后 Skill 写入 **Owner 的 custom 目录**，对该 Owner 后续所有 Thread 生效。

**本部署权限分工：**

| 步骤 | 谁 | API / 操作 | Internal Token + Owner |
|------|-----|------------|------------------------|
| 上传 `.skill` 到 Thread | **平台** | `POST /api/threads/{id}/uploads` | ✅ 可用 |
| 从上传文件安装到用户 | **运维（admin）** | `POST /api/skills/install` | ❌ 403（需 admin 角色） |
| 手动解压到用户目录 | **运维** | 文件系统 | 不经过 API |

> 实测（2026-07-20）：平台上传成功；同 Owner 调 `POST /api/skills/install` 返回 `403 Admin privileges required`；运维将 ZIP 解压到 `.deer-flow/users/zhangsan/skills/custom/` 后，`GET /api/skills/custom` 立即可见，**无需重启 Gateway**。

#### 4.6.1 本地准备 Skill 包

**目录结构示例：**

```text
invoice-check/
├── SKILL.md          # 必需，含 YAML frontmatter
└── references/       # 可选
    └── rules.md
```

`SKILL.md` 最小示例：

```yaml
---
name: invoice-check
description: 审查发票数据是否符合公司财务规范。用户要求校验发票时使用。
---

# Invoice Check Skill

（正文：步骤与约束）
```

**打成 `.skill`（任选其一）：**

```bash
# 方式 A：仓库自带打包脚本（会先校验 SKILL.md）
cd skills/public/skill-creator/scripts
python3 package_skill.py /path/to/invoice-check /tmp

# 方式 B：手动 zip（根目录保留 skill 文件夹名）
cd /path/to/parent
zip -r invoice-check.skill invoice-check/
```

#### 4.6.2 平台：创建 Thread 并上传

```bash
export GATEWAY="http://127.0.0.1:8001"
export INTERNAL_TOKEN="X-DeerFlow-Internal-Token-valid"
export OWNER="zhangsan"

# Step 1 — 创建 Thread（也可复用已有 thread_id）
THREAD_ID=$(curl -sS -X POST "${GATEWAY}/api/threads" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{"metadata":{"label":"skill-pack-test"}}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['thread_id'])")

# Step 2 — 上传 .skill（multipart 字段名必须是 files）
curl -sS -X POST "${GATEWAY}/api/threads/${THREAD_ID}/uploads" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -F "files=@/tmp/invoice-check.skill;type=application/octet-stream"
```

**上传成功响应要点：**

| 字段 | 说明 |
|------|------|
| `files[0].path` | 宿主机绝对路径，如 `.deer-flow/users/zhangsan/threads/{thread_id}/user-data/uploads/invoice-check.skill` |
| `files[0].virtual_path` | 安装 API 用的虚拟路径，如 **`/mnt/user-data/uploads/invoice-check.skill`** |
| `files[0].artifact_url` | 可下载该文件的 Gateway URL |

**确认文件在 Thread 中：**

```bash
curl -sS "${GATEWAY}/api/threads/${THREAD_ID}/uploads/list" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

> 上传到 **uploads** 目录；`path` 填响应里的 `virtual_path`（`/mnt/user-data/uploads/...`），不要写成 `outputs`。

#### 4.6.3 运维：通过 Install API 安装（需 admin）

Gateway 实现为 **JSON 请求体**（非 multipart 直传文件）：

```http
POST /api/skills/install
Content-Type: application/json
X-DeerFlow-Owner-User-Id: zhangsan   # 安装到该 Owner 的 custom 目录
```

**请求体：**

```json
{
  "thread_id": "149239e6-a530-4434-aff2-5c732bcc3057",
  "path": "/mnt/user-data/uploads/invoice-check.skill"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `thread_id` | 是 | 上传时使用的 Thread ID |
| `path` | 是 | 上传响应中的 `virtual_path` |

**成功响应（201/200）：**

```json
{
  "success": true,
  "skill_name": "invoice-check",
  "message": "Skill 'invoice-check' installed successfully"
}
```

落盘位置：`.deer-flow/users/zhangsan/skills/custom/invoice-check/`。

**平台 Internal Token 调用会失败（实测）：**

```json
{"detail":"Admin privileges required to manage skills."}
```

HTTP **403**。本部署无浏览器 admin 时，请用下方 4.6.4 运维落盘。

**常见错误：**

| HTTP | 原因 |
|------|------|
| 403 | 非 admin 调用 install |
| 404 | `thread_id` 或 `path` 错误；Owner 与 Thread 不一致 |
| 409 | 同名 custom Skill 已存在 |
| 400 | ZIP 内无合法 `SKILL.md` frontmatter；或 SkillScan 安全扫描拒绝 |

#### 4.6.4 运维：手动解压（本部署推荐）

平台完成上传后，将 **`Owner` + `thread_id` + 上传文件名**（如 `invoice-check.skill`）交给运维即可；**运维解压不需要 `virtual_path`**，磁盘路径固定为：

```text
.deer-flow/users/{Owner}/threads/{thread_id}/user-data/uploads/{filename}
```

运维在 Gateway 宿主机执行：

```bash
# 方式 A：从 Thread uploads 目录取已上传的包
THREAD_ID="149239e6-a530-4434-aff2-5c732bcc3057"
OWNER="zhangsan"
ARCHIVE=".deer-flow/users/${OWNER}/threads/${THREAD_ID}/user-data/uploads/invoice-check.skill"
TARGET=".deer-flow/users/${OWNER}/skills/custom"

mkdir -p "${TARGET}"
unzip -o "${ARCHIVE}" -d "${TARGET}"

# 方式 B：运维本地持有 .skill，直接解压到用户目录
unzip -o /tmp/invoice-check.skill -d .deer-flow/users/zhangsan/skills/custom/
```

解压后目录应为：

```text
.deer-flow/users/zhangsan/skills/custom/invoice-check/SKILL.md
```

**平台验证：**

```bash
curl -sS "${GATEWAY}/api/skills/custom" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: zhangsan"
```

响应中应出现 `"name":"invoice-check"`，`"category":"custom"`，`"enabled":true`。

#### 4.6.5 端到端流程图

```
运维/CI 打包 invoice-check.skill
        │
        ▼
平台 POST /api/threads          （Owner=zhangsan）
        │
        ▼
平台 POST .../uploads           （multipart files=@xxx.skill）
        │  返回 virtual_path=/mnt/user-data/uploads/xxx.skill
        ▼
   ┌────┴────┐
   │         │
有 admin    无 admin（本部署）
   │         │
   ▼         ▼
POST        运维 unzip 到
/api/skills/install   .deer-flow/users/zhangsan/skills/custom/
   │         │
   └────┬────┘
        ▼
GET /api/skills/custom  →  zhangsan 后续对话自动可用
```

---

### 4.7 HTTP 接口（平台 Internal Token 仅 GET）

平台侧用 Internal Token **只能读 Skill 列表/元数据**；写操作（install、reload、改 custom 内容等）需 admin 或由运维/对话替代（见下表）。

**统一请求头（三个 GET 均必填）：**

| 请求头 | 说明 |
|--------|------|
| `X-DeerFlow-Internal-Token` | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 业务用户，如 `zhangsan` |

#### 4.7.1 列出全部 Skill — `GET /api/skills`

返回该 Owner 可见的 **public + custom + legacy** Skill。响应体为 `{"skills":[...]}`，每项含 `name`、`description`、`category`（`public` / `custom` / `legacy`）、`enabled`、`editable` 等。

```bash
curl -sS "${GATEWAY}/api/skills" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

示例片段：

```json
{
  "skills": [
    {"name": "deep-research", "category": "public", "enabled": true, "editable": false},
    {"name": "invoice-test-check", "category": "custom", "enabled": true, "editable": true}
  ]
}
```

#### 4.7.2 单个 Skill 元数据 — `GET /api/skills/{skill_name}`

同上请求头；返回单个 Skill 对象（非 `{skills:[]}` 包装）。不存在时 **404**。

```bash
curl -sS "${GATEWAY}/api/skills/invoice-test-check" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

#### 4.7.3 仅 custom Skill — `GET /api/skills/custom`

同上请求头；仅返回该 Owner 的 **custom** Skill（不含 public/legacy）。响应格式同为 `{"skills":[...]}`。同一 Owner 下可并存多个 custom Skill（如 `invoice-check`、`invoice-test-check`、`order-review`）。

```bash
curl -sS "${GATEWAY}/api/skills/custom" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

> **与 MCP 区分**：Skill 按 **Owner 隔离**；MCP 为 **全站全局** 配置，见 **§5**。

#### 写接口（本部署一般不调用）

| 接口 | Gateway 要求 | 本部署替代方式 |
|------|--------------|----------------|
| `PUT /api/skills/{name}` | admin | 运维改 `extensions_config.json` 或 `_skill_states.json` |
| `POST /api/skills/install` | admin | 见 **§4.6.3**（Install API）；无 admin 时用 **§4.6.4**（运维解压） |
| `POST /api/skills/reload` | admin | 重启 Gateway |
| `PUT/DELETE /api/skills/custom/*` | admin | 对话让 Agent `skill_manage`，或运维改文件 |

---

### 4.8 场景速查

| 场景 | 谁 | 怎么做 |
|------|-----|--------|
| 全站开放 deep-research | 运维 | `extensions_config.json` + 重启 |
| 查 zhangsan 有哪些 Skill | 平台 | `GET /api/skills`，Owner=zhangsan |
| zhangsan 对话里用 Skill | 平台 | `POST /api/runs/stream`，Owner=zhangsan |
| zhangsan 自建 order-review | 平台 | Owner=zhangsan 发对话 + `skill_manage`；需 `skill_evolution.enabled` |
| 分发 `.skill` 给 zhangsan | 平台 + 运维 | 平台 `POST .../uploads`；把 **Owner + thread_id + 文件名** 给运维 unzip（§4.6.4）；或 admin 同用户 install（§4.6.3） |
| 限制 Agent 只用某几个 Skill | 平台 | `POST /api/agents`，`skills: [...]` |

### 4.9 注意事项

1. public Skill 未在 `extensions_config.json` 启用时，**任何 Owner** 的对话里都加载不到
2. custom Skill 默认创建即启用；若要关闭，运维编辑 `.deer-flow/users/{Owner}/skills/_skill_states.json`
3. 改 `extensions_config.json` 后**重启 Gateway**（不要依赖 reload API）
4. 勿在 Skill 中重复实现内置文件工具能力

---

## 五、MCP 工具接入

MCP（Model Context Protocol）用于挂载外部工具服务：GitHub、PostgreSQL、企业内部 HTTP API 等。配置后 Agent 在对话中自动发现 MCP 工具；模型侧工具名带 **`{server}_` 前缀**（如 `github_create_issue`）。

### 5.1 角色分工（本部署）

| 角色 | 职责 |
|------|------|
| **运维** | 编辑根目录 `extensions_config.json` 的 `mcpServers`（或 admin 调 `/api/mcp/*`）；配置 Gateway 环境变量；重启或 `cache/reset` |
| **平台** | **不能**调用 `/api/mcp/*`（需 admin）；通过 **`POST /api/runs/stream`** 正常发对话，Agent 自动使用已启用的 MCP 工具 |

**重要**：MCP 是 **全站全局** 配置，**不按 Owner 隔离**。`zhangsan`、`lisi` 等同一次 run 里看到的 MCP 工具集相同；差异来自 Skill、Agent、Thread 等 Owner 级资源（见 **§4**、**§6**）。

### 5.2 配置文件

根目录 `extensions_config.json` → `mcpServers`。下列为 **stdio + 远程** 典型写法合集；**生产环境通常只启用需要的 server**（其余保持 `"enabled": false`）。

```json
{
  "mcpServers": {
    "github": {
      "enabled": false,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
      "tool_call_timeout": 60,
      "description": "GitHub 仓库操作（需 Gateway 环境 export GITHUB_TOKEN）"
    },
    "postgres": {
      "enabled": false,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@127.0.0.1:5432/mydb"],
      "routing": {
        "mode": "prefer",
        "priority": 50,
        "keywords": ["数据库", "SQL", "订单", "用户"]
      },
      "description": "PostgreSQL（Gateway 宿主机 Postgres 须已监听）"
    },
    "sqlite-local": {
      "enabled": false,
      "type": "stdio",
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "/data/demo/app.db"],
      "tool_call_timeout": 60,
      "description": "本地 SQLite 文件库（--db-path 为 Gateway 可访问绝对路径）"
    },
    "everything-demo": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-everything"],
      "tool_call_timeout": 30,
      "description": "MCP 官方测试 server（无需密钥，验证 stdio 链路）"
    },
    "corp-api": {
      "enabled": false,
      "type": "http",
      "url": "https://mcp.corp.example.com/v1",
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.corp.example.com/oauth/token",
        "grant_type": "client_credentials",
        "client_id": "$MCP_OAUTH_CLIENT_ID",
        "client_secret": "$MCP_OAUTH_CLIENT_SECRET",
        "scope": "mcp.read"
      },
      "description": "远程 HTTP MCP + OAuth（企业统一网关）"
    },
    "internal-search": {
      "enabled": false,
      "type": "sse",
      "url": "https://mcp-internal.corp.example.com/sse",
      "headers": {"X-Api-Key": "$INTERNAL_MCP_API_KEY"},
      "description": "远程 SSE MCP（内网托管）"
    }
  },
  "skills": {}
}
```

| `mcpServers` 键 | 类型 | 说明 |
|-----------------|------|------|
| `github` | stdio + `npx` | 读/写 GitHub；模型侧工具名如 `github_create_issue` |
| `postgres` | stdio + `npx` | 查本机/内网 Postgres；`args` 末尾为连接串 |
| `sqlite-local` | stdio + `uvx` | 轻量 SQLite；等价于 `uvx mcp-server-sqlite --db-path …` |
| `everything-demo` | stdio + `npx` | **冒烟推荐**；等价于 `npx -y @modelcontextprotocol/server-everything` |
| `corp-api` | `http` + `oauth` | 连企业 HTTP MCP；密钥用 `$VAR` |
| `internal-search` | `sse` + `headers` | 连内网 SSE MCP 端点 |

- 环境变量用 **`$VAR`** 引用，**不要**在 JSON 里明文写密钥。
- `"enabled": false` 的 server **不会**加载。
- 改配置后需 **重启 Gateway**，或 admin **`PUT /api/mcp/config`**（见 **§5.8.2**）热加载。
- admin **`POST /api/mcp/cache/reset`** 仅清当前进程 MCP **工具缓存**，**不会**重新读磁盘上的 `extensions_config.json`。

### 5.3 本地 stdio vs 远程 sse/http：怎么选

| 维度 | **本地 stdio**（`type: "stdio"` + `command`） | **远程 sse / http**（`type: "sse"` \| `"http"` + `url`） |
|------|-----------------------------------------------|--------------------------------------------------------|
| **进程在哪跑** | Gateway **同一台机器**上由 DeerFlow **拉起子进程** | Gateway **连外部 URL**，不本地起包 |
| **典型包/服务** | npm 的 `npx …`、Python 的 `uvx …` | 企业已部署的 MCP Gateway、SaaS MCP 端点 |
| **网络** | 多数只需访问本机 DB/文件；拉包时可能要外网 npm/PyPI | 必须 Gateway 能访问 `url`（内网/VPN/公网） |
| **密钥放哪** | `env` 里 `$VAR`，由 Gateway **进程环境**注入子进程 | 常配 `oauth` 或 `headers`；密钥仍在环境变量 |
| **适合** | 官方 MCP 包、连本机 Postgres/SQLite、GitHub 类工具 | 统一托管、多租户、已有 HTTP MCP 服务、不想在 Gateway 装 Node/Python |

有现成 **npm/PyPI MCP 包**、数据/服务在 Gateway 本机或可直连 → 用 **stdio**；已有团队维护的 **HTTP/SSE MCP 服务** → 用 **远程**。具体 JSON 字段见 **§5.2** 各 server 块。

### 5.4 `command` / `args` 怎么填（stdio）

Gateway 执行逻辑等价于：

```bash
# "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]
npx -y @modelcontextprotocol/server-github

# "command": "uvx", "args": ["mcp-server-sqlite", "--db-path", "/data/app.db"]
uvx mcp-server-sqlite --db-path /data/app.db
```

| 字段 | 含义 |
|------|------|
| `command` | 可执行文件名，**须在白名单内**（默认 `npx`、`uvx`） |
| `args` | 参数数组；**不要**把整条命令写进一个字符串 |
| `env` | 仅 stdio：注入子进程；值写 `$VAR` 从 Gateway 环境解析 |

| type | 必填字段 | 说明 |
|------|----------|------|
| **`stdio`** | `command` + `args` | 本地子进程 |
| **`sse` / `http`** | `url` | 远程端点；可选 `headers`、`oauth` |

| command | 含义 | 示例 |
|---------|------|------|
| **`npx`** | Node.js 包运行器 | `"args": ["-y", "@modelcontextprotocol/server-github"]` |
| **`uvx`** | Python 包运行器 | `"args": ["mcp-server-sqlite", "--db-path", "/data/app.db"]` |

Gateway 默认 stdio 仅允许 `npx`、`uvx`；可用 `DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST` 扩展。

OAuth、`mcpInterceptors` 等见 [backend/docs/MCP_SERVER.md](../backend/docs/MCP_SERVER.md)。

### 5.5 动手试：在本机启用 `everything-demo`（stdio）

**1. 编辑 `extensions_config.json`**（见 **§5.2** 中 `everything-demo` 块），Gateway 机器需 **Node.js + npx**。

**2. 让 Gateway 读到新配置**

| 方式 | 说明 |
|------|------|
| **重启 Gateway** | `make dev` / docker 重启后自动读文件 |
| **admin `PUT /api/mcp/config`** | 热写入并 `reload_extensions_config`（见 **§5.8.2**） |
| **`POST /api/mcp/cache/reset`** | 仅清 MCP **工具缓存**；**不会**重新读磁盘上的 `extensions_config.json` |

改 JSON 文件后若只调 `cache/reset` 而 Gateway 未重启，admin `GET /api/mcp/config` 里可能仍看不到新 server。

**3. 平台发对话**（Internal Token + Owner）：

```bash
export GATEWAY=http://127.0.0.1:8001
export INTERNAL_TOKEN=X-DeerFlow-Internal-Token-valid   # 与 config 中 internal auth 一致
export OWNER=zhangsan
export THREAD_ID=<你的 thread_id>

curl -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{
    "thread_id": "'"${THREAD_ID}"'",
    "input": {"messages": [{"role": "user", "content": "请调用 everything-demo MCP 的 echo 工具，参数 message=hello-deerflow-mcp"}]}
  }'
```

**预期 SSE 片段**（本环境已验证）：

- 模型 tool call：`everything-demo_echo`（规则：`{mcpServers 的 key}_{MCP 原始工具名}`）
- 工具返回：`Echo: hello-deerflow-mcp`
- 最终 assistant 回复同 echo 结果

验通后可 `"enabled": false`，再按需启用 **github**（配 `GITHUB_TOKEN`）或 **postgres**（本机有库）等。

> 无效的 `mcpInterceptors`（如示例 `my_package.mcp.auth`）一般只打 warning，不阻止 MCP 加载；生产请改真实路径或 `"mcpInterceptors": []`。

### 5.6 超时：tool_call_timeout

| 传输 | `tool_call_timeout` |
|------|---------------------|
| **`stdio`** | **生效**：单次 MCP tool call 上限（秒），如 `"tool_call_timeout": 60` |
| **`sse` / `http`** | **不生效**（配置了会打 warning）；依赖传输层 / 远端服务超时 |

### 5.7 路由提示 routing（可选）

**软引导**：在 system prompt 注入 `<mcp_routing_hints>`，帮助模型**优先**选用某 MCP 工具；**不会禁止**内置工具或其他 MCP。

```json
"routing": {
  "mode": "prefer",
  "priority": 50,
  "keywords": ["查库", "订单表"]
}
```

| 字段 | 说明 |
|------|------|
| `mode` | `prefer` 才生效；`off` 关闭 |
| `priority` | 0–100，越高越靠前展示 |
| `keywords` | 与**最新用户消息**做**子串**匹配（区分大小写策略见实现）；词要具体，避免 `api` 误匹配 `rapid` |

还可在 `tools.<原始工具名>.routing` 上为单个 MCP 工具覆盖上述字段（工具名用 MCP server 原始名，**不含** `{server}_` 前缀）。

### 5.8 HTTP 管理接口（admin only）

> **平台 Internal Token 调用 `/api/mcp/*` 会 403。** 下列接口供 **运维 / admin** 排查或热更新；日常推荐直接改 `extensions_config.json` + 重启。

**Admin 登录（form + Cookie + CSRF）：**

```bash
ADMIN_COOKIE=".deer-flow/verify-api/admin.cookies"
ADMIN_EMAIL="${DEER_FLOW_ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${DEER_FLOW_ADMIN_PASSWORD:-AdminPass123!}"

curl -sS -X POST "${GATEWAY}/api/v1/auth/login/local" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -c "${ADMIN_COOKIE}" \
  -d "username=${ADMIN_EMAIL}&password=${ADMIN_PASSWORD}"

CSRF="$(grep csrf_token "${ADMIN_COOKIE}" | awk '{print $NF}')"
```

密码含 `!` 等 shell 特殊字符时，`-d` 建议用**单引号**包裹整段 `username=...&password=...`（zsh/bash）。

#### 5.8.1 查看配置 — `GET /api/mcp/config`

返回当前 MCP 配置；**密钥字段脱敏**（显示 `***`）。

```bash
curl -sS "${GATEWAY}/api/mcp/config" \
  -H "X-CSRF-Token: ${CSRF}" \
  -b "${ADMIN_COOKIE}"
```

#### 5.8.2 更新配置 — `PUT /api/mcp/config`

**请求体**键名为 **`mcp_servers`**（snake_case），写入 `extensions_config.json` 并热重载。已有 `$VAR` 占位符会被保留。

```bash
curl -sS -X PUT "${GATEWAY}/api/mcp/config" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: ${CSRF}" \
  -b "${ADMIN_COOKIE}" \
  -d '{
    "mcp_servers": {
      "github": {
        "enabled": true,
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}
      }
    }
  }'
```

> **注意**：`PUT` 会**替换**请求体中的整个 `mcp_servers` 对象。更新前务必先 **`GET /api/mcp/config`**，在完整列表上修改后再提交，避免误删其他 server。

#### 5.8.3 重置工具缓存 — `POST /api/mcp/cache/reset`

清空**当前 Gateway 进程**内 MCP 工具缓存与会话池；下次 run 重新连接 MCP。

```bash
curl -sS -X POST "${GATEWAY}/api/mcp/cache/reset" \
  -H "X-CSRF-Token: ${CSRF}" \
  -b "${ADMIN_COOKIE}"
```

多 Gateway 实例时，每个实例需各自 reset，或统一重启。

### 5.9 平台如何使用 MCP

平台**无需**单独「调用 MCP API」：

1. 运维确保目标 server 在 `extensions_config.json` 中 **`enabled: true`**，且 Gateway 环境变量齐全。
2. 平台按 **§2–3** 创建 Thread、`POST /api/runs/stream`，在 `messages` 里描述任务（如「查 GitHub issue #123」）。
3. Agent 自行选择 `{server}_*` 工具；在 SSE 事件或 Langfuse trace 中可看到 tool call。

若需**硬限制**某 Agent 只能用部分工具，用 **§6** 的 `tool_groups` / Agent 策略，而非 MCP routing。

### 5.10 接入 checklist（运维）

1. `cp extensions_config.example.json extensions_config.json`
2. 在 `mcpServers` 添加 server 块，`"enabled": true`
3. 在 Gateway 运行环境配置所需环境变量（如 `GITHUB_TOKEN`）
4. 重启 Gateway，或 admin `POST /api/mcp/cache/reset`
5. 平台发起对话，在 SSE / Langfuse trace 中确认 Agent 调用了 `{server}_*` 工具

### 5.11 注意事项

- **不要**为 DeerFlow workspace 再挂 MCP **filesystem** 服务器 — 与内置 `read_file` / `write_file` 路径语义冲突（见 [backend/docs/MCP_SERVER.md](../backend/docs/MCP_SERVER.md)）
- MCP 与 Skill 是**独立**扩展：`extensions_config.json` 里 `mcpServers` 与 `skills` 并列，互不影响
- 自定义拦截器：顶层 `mcpInterceptors` 数组，用于注入 per-request 头等

---

## 六、自定义 Agent API

自定义 Agent 为某 **Owner**（如 `zhangsan`）配置独立的 **SOUL.md**（人格/边界）、模型、工具组、Skill 白名单。对话时在 `assistant_id` 指定 Agent 名称即可。

**运维前置**：`config.yaml` 启用：

```yaml
agents_api:
  enabled: true
```

**存储路径**：`.deer-flow/users/{Owner}/agents/{name}/`（`SOUL.md` + `config.yaml`）。

**本章所有接口统一请求头（除非另说明）：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 是 | Agent 归属的业务用户，如 `zhangsan` |

> Agent 按 **Owner 隔离**：`zhangsan` 创建的 Agent，`lisi` 无法通过 API 读取（除非换 Owner 头且该 Agent 本不属于 lisi）。

### 6.1 创建 Agent — `POST /api/agents`

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `Content-Type` | 是 | `application/json` |
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 是 | Agent 所属 Owner |

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

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 是 | 只返回该 Owner 下的 Agent |

**请求体**：无

```bash
curl -sS "${GATEWAY}/api/agents" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

### 6.3 获取单个 Agent — `GET /api/agents/{name}`

**请求头**：同 6.2（`X-DeerFlow-Owner-User-Id` **必填**）

**路径参数**

| 参数 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Agent 名称，如 `zhangsan-agent` |

```bash
curl -sS "${GATEWAY}/api/agents/zhangsan-agent" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

### 6.4 检查名称是否可用 — `GET /api/agents/check?name={name}`

**请求头**：同 6.2（`X-DeerFlow-Owner-User-Id` **必填**）

**Query 参数**

| 参数 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 待检查的 Agent 名称 |

```bash
curl -sS "${GATEWAY}/api/agents/check?name=my-new-agent" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

响应：`{"available": true, "name": "my-new-agent"}`

### 6.5 更新 Agent — `PUT /api/agents/{name}`

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `Content-Type` | 是 | `application/json` |
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 是 | Agent 所属 Owner |

**请求体**（字段均为可选，只更新提供的项）：

| 参数 | 说明 |
|------|------|
| `description` | 描述 |
| `model` | 模型 |
| `tool_groups` | 工具组 |
| `skills` | Skill 白名单 |
| `soul` | SOUL.md 正文 |

**示例**

```bash
curl -sS -X PUT "${GATEWAY}/api/agents/zhangsan-agent" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{"description": "更新后的描述", "tool_groups": ["web", "file:read", "file:write"]}'
```

### 6.6 删除 Agent — `DELETE /api/agents/{name}`

**请求头**

| 参数 | 必填 | 说明 |
|------|------|------|
| `X-DeerFlow-Internal-Token` | 是 | Internal Token |
| `X-DeerFlow-Owner-User-Id` | 是 | Agent 所属 Owner |

**请求体**：无

```bash
curl -sS -X DELETE "${GATEWAY}/api/agents/zhangsan-agent" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
```

成功返回 **204**。若遇 307 重定向，加 `-L` 且 URL **不要** trailing slash。

### 6.7 使用自定义 Agent 对话

在 `POST /api/runs/stream` 中指定 `assistant_id`；**Owner 头必须与创建 Agent 时一致**。

**请求头**（除通用对话头外，Owner **必填**）：

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

**人在回路（HITL）**：Agent 执行过程中暂停，等待**用户（Owner）**做出选择或输入文字；用户解析 SSE（或查 Thread state）后，用**同一 Owner** 再调 `POST /api/runs/stream` 携带 `human_input_response` 续跑。

> **参与方（仅两方）**
>
> | 参与方 | 是谁 | 做什么 |
> |--------|------|--------|
> | **用户（Owner）** | `X-DeerFlow-Owner-User-Id`（如 `zhangsan`） | 发任务、看 Agent 提出的问题、选择或输入答案、发起续跑请求 |
> | **DeerFlow** | Gateway + Agent | 调用 `ask_clarification` 后暂停 run；收到 `human_input_response` 后继续推理 |
>
> HITL 里没有第三角色：用户通过 HTTP API 直接与 DeerFlow 交互（请求头带 Internal Token + Owner ID）。

DeerFlow 内置机制是 **`ask_clarification` 工具**：模型调用后 run 暂停；用户从 SSE（或 `GET /api/threads/{id}/state`）读出 pending 问题，选定答案后 `POST /api/runs/stream` 携带 `human_input_response` 续跑。

**本章所有 HITL 续跑请求统一请求头：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `Content-Type` | 是 | `application/json` |
| `Accept` | 建议 | `text/event-stream` |
| `X-DeerFlow-Internal-Token` | 是 | Internal Token（调用凭证） |
| `X-DeerFlow-Owner-User-Id` | 是 | **须与触发 HITL 的 Thread 同一用户**（如 `zhangsan`） |

### 7.1 DeerFlow 内置 HITL 机制（三个组件）

DeerFlow **不提供**独立的「工单暂停 API」；人在回路完全由 **`ask_clarification` 工具 + 中间件拦截 + 续跑消息** 驱动。一次 HITL 轮次的生命周期如下：

```text
用户发任务 (POST /api/runs/stream)
    → 模型调用 ask_clarification
    → ClarificationMiddleware 拦截（工具体不真正执行）
    → 写入 ToolMessage + artifact.human_input
    → 本轮 run 结束（SSE 最后一条 values 含 pending 问题）
用户看到问题 → 选择/输入答案
    → 用户 POST /api/runs/stream（同一 thread_id + Owner）
    → 消息带 hide_from_ui + human_input_response
    → Agent 读取答案，继续推理（可能再次 ask_clarification → 下一轮）
```

| 组件 | 作用 |
|------|------|
| **`ask_clarification` 工具** | 模型在信息不足、方案歧义或须用户确认时**主动调用**；参数含 `question`、`clarification_type`、可选 `options` |
| **`ClarificationMiddleware`** | 在工具节点**执行前拦截**该调用；格式化可读 `ToolMessage.content`；在 `artifact.human_input` 写入结构化 `human_input_request`；**结束当前 run**（不继续后续工具） |
| **用户的续跑消息** | 用户发起的 `POST /api/runs/stream`：`input.messages` 中一条 `role: human`，`additional_kwargs.hide_from_ui: true`，以及 `human_input_response` 绑定上一步的 `request_id` |

**关键字段对应关系**

| SSE / 请求字段 | 说明 |
|----------------|------|
| `artifact.human_input.request_id` | 固定格式 `clarification:{tool_call_id}`，续跑时必须原样回填 |
| `artifact.human_input.tool_call_id` | 与上方 `{tool_call_id}` 相同（不含 `clarification:` 前缀） |
| `human_input_response.request_id` | **必须等于** pending 问题的 `request_id`；Agent 重新提问会生成新 ID，旧 ID 失效 |
| `human_input_response.value` | 实际答案；**须与** `messages[0].content` **语义一致**（模型主要读 `content`） |
| `human_input_response.option_id` | 选择题可选；对应 SSE 里 `options[n].id`（`option-1`、`option-2`…） |

> **与 LangGraph `interrupt` 的区别**：用户侧 HITL **只需**本章 API。`interrupt_before` / `interrupt_after` 是图内部调试用，不等同于 `ask_clarification` 的 HITL 语义。

### 7.2 应用场景：对话补全 vs 动作前确认

两类需求都走**同一套 HITL API**；差异在于 Agent 为何暂停、用户如何作答。

#### 7.2.1 对话补全（模型主动问）

| 维度 | 说明 |
|------|------|
| **典型问题** | 信息缺失、需求歧义、多种方案选哪一个 |
| **谁触发暂停** | **模型**调用 `ask_clarification` |
| **clarification_type** | `missing_info`、`ambiguous_requirement`、`approach_choice` 等 |
| **用户侧** | 从 SSE 取问题 → 选择或输入 → POST 续跑 |
| **确定性** | **软**：模型可能该问没问 |

示例：`zhangsan` 发任务 → Agent 问「部署到哪个环境？」→ `zhangsan` 选「测试环境」→ 同一用户 POST 续跑。

#### 7.2.2 动作前确认（须用户确认后再继续）

| 维度 | 说明 |
|------|------|
| **典型问题** | 执行某操作**之前**须用户**确认、单选或输入**（覆盖文件、调外部 API、批量重试等） |
| **业务要求** | 卡点在 SOUL/Skill 或拆成两次 run 中约定，不能仅靠模型「自觉」 |
| **DeerFlow 机制** | `ask_clarification` 暂停 + `human_input_response` 续跑 |
| **确定性** | 硬卡点见 **§7.2.4 模式 B** |

示例（用户 `zhangsan`）：

```text
zhangsan 发：「对订单 #123 执行重试」
    → Agent ask_clarification（risk_confirmation，options: [执行, 取消]）
    → run 暂停
    → zhangsan 选「执行」
    → zhangsan POST 续跑（human_input_response）
    → Agent 继续后续工具 / MCP
```

| clarification_type | 用户操作 | 示例 |
|--------------------|------------|------|
| `risk_confirmation` | 确认/取消 | 覆盖数据、批量重试 |
| `approach_choice` | 单选 | 选部署方案 A/B |
| `missing_info` | 文本或选项 | 补单号、设备编号 |
| `ambiguous_requirement` | 澄清 | 「重启服务」指哪台 |
| `suggestion` | 采纳/拒绝 | Agent 建议是否跳过某步 |

`input_mode`：**有 `options` → 选择题**；**无 `options` → 自由文本**。

#### 7.2.3 能力边界

| 能力 | 说明 |
|------|------|
| **支持** | 暂停 run；用户**选择/输入**；同 Thread 多轮 HITL；`GET .../state` 轮询 pending |
| **不支持（开箱）** | 按业务「节点名」自动停；用 **§7.2.4** 实现 |
| **`interrupt_before` / `interrupt_after`** | LangGraph 图内部调试用；用户侧**不必用** |
| **Guardrails** | 工具 **ALLOW/DENY**，**不暂停**等人输入 |
| **定时 / 非交互 run** | 无 `ask_clarification`；须拆 run，不能靠本章 HITL |

#### 7.2.4 推荐用法（用户 + DeerFlow）

**模式 A — Agent + SOUL（软保证）**

SOUL 写明：涉及 {动作} 必须先 `ask_clarification`（`risk_confirmation` + `options`）。  
用户收到问题后作答并续跑即可。

**模式 B — 拆成两次 run（硬卡点）**

```text
Run1: 用户发任务 → Agent 输出「待确认」的结构化结果 → run 结束
用户: 确认选择/输入文字
Run2: 同一 thread_id + Owner，POST 续跑（messages 带用户结论）
```

卡点由**用户是否在 Run2 前确认**保证；DeerFlow 只做两段推理。

**模式 C — 同 Thread 多轮 HITL（API 原生）**

Agent `ask_clarification` → 用户作答 → `human_input_response` → 循环（**§7.3**、**§7.6**）。  
适合对话式；SOUL/Skill 约束「执行 X 前先问」。

**模式 D — 限工具 + Clarify**

`tool_groups` 收紧 + SOUL 要求敏感操作前 `risk_confirmation`。

**多轮 HITL 统一流程（模式 B/C）：**

1. 监听 SSE / 轮询 state → 发现 `human_input_request`
2. 用户阅读 `question` / `options`，作出选择或输入
3. 用户 POST **§7.5** 续跑（**同一 `X-DeerFlow-Owner-User-Id`**）
4. **`thread_id` 不变**；换用户 ID 会 404 / 续跑失败

### 7.3 完整走查：部署任务多轮 HITL（API 逐步示例）

以下示例与仓库内 JSON **一一对应**，可直接复制执行。环境变量：

```bash
export GATEWAY="http://127.0.0.1:8001"
export INTERNAL_TOKEN="X-DeerFlow-Internal-Token-valid"
export OWNER="zhangsan"
```

**场景**：用户要求 Agent 部署服务；Agent 不确定环境时必须先问，不能猜测。实际跑通时 Agent 常会**连续多轮**追问（环境 → 服务器类型 → 部署方式等），每轮流程相同。

#### Step 1 — 发起任务，触发第一次 `ask_clarification`

`scripts/verify-api/hitl-step1-ask.json` 要点：`thread_id` 固定（如 `hitl-api-test-007`），用户消息要求 Agent 在不确定环境时必须调用 `ask_clarification`。

```bash
curl -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d @scripts/verify-api/hitl-step1-ask.json \
  | tee /tmp/hitl-step1.sse
```

**从 SSE 末尾解析**（`event: values` → `messages` 最后一条 `type: "tool"`, `name: "ask_clarification"`）：

| 字段 | 示例值 | 用途 |
|------|--------|------|
| `tool_call_id` | `call_tZpujZ1OSM2BHYApTxX7jg` | 拼 `request_id` |
| `request_id` | `clarification:call_tZpujZ1OSM2BHYApTxX7jg` | Step 2 必填 |
| `question` | `您希望将服务部署到哪个环境？` | 展示给用户 |
| `options[1]` | `{"id":"option-2","label":"测试环境","value":"测试环境"}` | 用户选「测试环境」时用 |

此时 **run 已结束**；最后一条 `values` 含 `artifact.human_input.kind: "human_input_request"`，即 pending 状态。

#### Step 2 — 用户选「测试环境」，续跑

**续跑三要素**：① 同一 `thread_id`；② 同一 `X-DeerFlow-Owner-User-Id`；③ `human_input_response.request_id` = Step 1 的 `request_id`。

将 Step 1 解析出的 `tool_call_id` 填入 `hitl-step2-reply.json`（或动态生成 JSON）：

```json
{
  "assistant_id": "lead_agent",
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
          "request_id": "clarification:call_tZpujZ1OSM2BHYApTxX7jg",
          "response_kind": "option",
          "option_id": "option-2",
          "value": "测试环境"
        }
      }
    }]
  },
  "config": {"configurable": {"thread_id": "hitl-api-test-007"}},
  "context": {"subagent_enabled": false, "is_plan_mode": false, "thinking_enabled": false, "model_name": "chatling-plus"},
  "on_disconnect": "continue"
}
```

```bash
curl -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d @scripts/verify-api/hitl-step2-reply.json \
  | tee /tmp/hitl-step2.sse
```

Agent 收到答案后会继续推理。**若仍缺信息，会再次 `ask_clarification`**（多轮 HITL）。例如实测（`thread_id: hitl-api-test-002`）在用户选「测试环境」后，Agent 又依次问了：

```text
Round 1  目标环境？       → 用户：测试环境   (request_id: clarification:call_0NRv_...)
Round 2  服务器类型？     → 用户：Windows    (request_id: clarification:call_HdOA_...)
Round 3  部署方式？       → 用户：手动部署
```

每一轮 SSE 末尾都会出现**新的** `request_id`；须从**最新** pending 问题取值，不能用历史 ID。

若 Agent 认为信息已够（如今日 `hitl-api-test-007` 实测），Step 2 后直接给出文本回复或调用 `web_search` / `write_file` 等工具，**不再**出现新的 `ask_clarification`——这也是正常行为。

#### Step 3 及以后 — 同一 Thread 循环

每一轮重复：**解析最新 SSE → 用户作答 → POST 续跑**。`hitl-step3-reply.json` 示例为用户选 **Windows**：

```json
"request_id": "clarification:call_<本轮新的 tool_call_id>",
"response_kind": "option",
"option_id": "option-2",
"value": "Windows",
"content": "Windows"
```

实测多轮顺序**因模型与上下文而异**，常见模式：

```text
Round 1  目标环境？     → 用户：测试环境
Round 2  服务器类型？   → 用户：Windows
Round 3  部署方式？     → 用户：手动部署 / 自动化部署
         → Agent 继续给出后续步骤或调用工具
```

**判定是否仍有 pending**：遍历 `messages`，找出所有 `human_input_response.request_id` 已回复的 ID；最后一条 `ask_clarification` 的 `request_id` **不在**已回复集合中 → 仍需用户输入。

**多轮 HITL 伪代码（用户侧）**

```python
thread_id = "hitl-api-test-007"
owner = "zhangsan"
while True:
    sse = post_runs_stream(messages=[...], thread_id=thread_id, owner=owner)
    pending = parse_pending_ask_clarification(sse)  # artifact.human_input
    if not pending:
        break  # run 正常结束，无待回复问题
    answer = user_chooses_or_types(pending["question"], pending.get("options"))
    post_runs_stream(
        messages=[{
            "role": "human",
            "content": answer["value"],
            "additional_kwargs": {
                "hide_from_ui": True,
                "human_input_response": {
                    "version": 1,
                    "kind": "human_input_response",
                    "source": "ask_clarification",
                    "request_id": pending["request_id"],
                    "response_kind": "option" if answer.get("option_id") else "text",
                    "option_id": answer.get("option_id"),
                    "value": answer["value"],
                },
            },
        }],
        thread_id=thread_id,
        owner=owner,
    )
```

#### 一键验证（Step 1 + Step 2）

```bash
bash scripts/verify-api/test-human-in-the-loop.sh
```

脚本自动：Step 1 → 从 SSE 提取 `tool_call_id` → 生成 Step 2 JSON → 续跑。多轮时重复 Step 2 逻辑，或手动改 `hitl-step2-reply.json` / `hitl-step3-reply.json` 中的 `request_id` 与 `value`。

### 7.4 识别待回复问题

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

### 7.5 回复请求格式

**请求头**：见本章开头统一请求头表（`X-DeerFlow-Owner-User-Id` **必填**）

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
| `request_id` | 是 | 来自 **§7.4**，必须是**当前 pending** 问题的 ID |
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
          "request_id": "clarification:call_tZpujZ1OSM2BHYApTxX7jg",
          "response_kind": "option",
          "option_id": "option-2",
          "value": "测试环境"
        }
      }
    }]
  },
  "config": {"configurable": {"thread_id": "hitl-api-test-007"}}
}
```

**自由文本回复**（无需 `option_id`）：

```json
"response_kind": "text",
"value": "我们用的是 Kubernetes 集群"
```

### 7.6 多轮 HITL 流程

**示例 A — 对话补全**（用户 `zhangsan`）：

```
Step1  zhangsan POST runs/stream → Agent ask_clarification（目标环境）
Step2  zhangsan 解析 SSE、选「测试环境」→ POST 续跑 → Agent 再问
Step3  zhangsan 再次 POST 续跑 → Agent 继续
```

**示例 B — 动作前确认**（用户 `zhangsan`）：

```
Step1  zhangsan：「对批次 B-2026 重新质检」→ Agent ask_clarification
        （risk_confirmation，options: [确认执行, 取消]）
Step2  zhangsan 选「确认执行」→ POST human_input_response
Step3  Agent 继续调用工具 / MCP
```

每一步从**最新** SSE 取 `request_id`；**`X-DeerFlow-Owner-User-Id` 全程为同一用户**（如 `zhangsan`）。

### 7.7 关键注意事项（必读）

| # | 规则 |
|---|------|
| 1 | **`content` 与 `value` 必须一致**。LLM 主要读 `content`；若 content 写「测试环境」而 value 写「Windows」，会导致 Agent 行为异常 |
| 2 | **`request_id` 必须对应当前 pending 问题**，不能用历史轮次 ID |
| 3 | `option_id` 按 SSE 中 options 顺序（`option-1`、`option-2`…）；后端不校验 option_id 与 value 是否匹配，用户侧自行保证一致。**解析 `tool_call_id` 时须取 `artifact.human_input.tool_call_id` 或 AI `tool_calls[].id`，不要误取 options 里的 `option-1`** |
| 4 | 可简写 `content` 为纯答案（如 `"Windows"`），不必重复完整问句 |
| 5 | 建议 JSON 放文件用 `-d @file.json`；HITL 请求须带齐 Internal Token 与 Owner 头 |
| 6 | 续跑时的 Owner 与 Thread 首聊时不一致会导致 404 或续跑失败 |

### 7.8 验证脚本

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
1. 配置 GATEWAY、INTERNAL_TOKEN；每个 End User 固定一个 OWNER（如 `zhangsan`）
2. 所有 API 均带 `X-DeerFlow-Internal-Token` + `X-DeerFlow-Owner-User-Id`（必填）
3. POST /api/threads（可选：预置 thread_id / metadata）
4. POST /api/runs/stream → 解析 SSE metadata，持久化 thread_id
5. 循环：用户消息 → 平台代该 Owner 调 runs/stream（同一 Owner + thread_id）
6. 遇 ask_clarification → 平台向**该 Owner** 收集选择/文字 → 代其 POST human_input_response 续跑（Owner 不变）
7. 需要文件 → POST /api/threads/{id}/uploads（Owner 必填）→ 消息引用虚拟路径
8. 需要专属 Agent → POST /api/agents（Owner 必填）→ assistant_id 指向该 Agent
```

### A.2 其他 HTTP 接口速查

以下接口同样需 **`X-DeerFlow-Internal-Token` + `X-DeerFlow-Owner-User-Id`（必填）**（`/api/models` 若 Gateway 未强制 Owner，仍建议始终带上以保持隔离一致）：

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
| 404 Thread | **Owner 头必填但未传**，或与 Thread 创建时不一致；或 `thread_id` 错误 |
| 409 同 thread 第二个 run | 默认 `multitask_strategy: reject`；等待上一个结束或设 `interrupt` |
| HITL 回复后重复提问 | `request_id` 过期，或 `content`/`value` 不一致 |
| search 查不到 Thread | **Owner 头不一致**；或 `metadata` 过滤条件不匹配 |
| Agent API 403 | `agents_api.enabled: false` |
| curl JSON 报错 | 使用 `-d @file.json` |

### A.4 延伸阅读

- [backend/docs/API.md](../backend/docs/API.md) — 完整 API 参考
- [backend/docs/MCP_SERVER.md](../backend/docs/MCP_SERVER.md) — MCP 详细配置
- [Install.md](../Install.md) — 安装与启动

---

*文档版本：2026-07。接口以 Gateway 源码为准，升级后请以 `backend/docs/API.md` 核对。*
