# DeerFlow 使用指南（HTTP 集成版）

本文面向**平台侧 / 业务系统集成**，说明如何通过 Gateway HTTP API 使用 DeerFlow：创建会话、流式对话、Thread 管理、人在回路（HITL）、自定义 Agent、Skills 与 MCP 工具接入。

> **服务入口**
> - 开发/生产统一入口（Nginx）：`http://127.0.0.1:2026`
> - Gateway 直连（调试）：`http://127.0.0.1:8001`
> - LangGraph 兼容路径：`/api/langgraph/*` 会被 Nginx 重写到 Gateway 原生 `/api/*`

---

## 目录

1. [认证与用户隔离](#1-认证与用户隔离)
2. [Thread 生命周期](#2-thread-生命周期)
3. [对话接口 `/api/runs/stream`](#3-对话接口-apirunsstream)
4. [人在回路 HITL](#4-人在回路-hitl)
5. [自定义 Agent API](#5-自定义-agent-api)
6. [Skills 接入](#6-skills-接入)
7. [MCP 工具接入](#7-mcp-工具接入)
8. [其他常用接口](#8-其他常用接口)
9. [集成建议与排错](#9-集成建议与排错)

---

## 1. 认证与用户隔离

DeerFlow 有两套调用方式：

| 场景 | 认证方式 |
|------|----------|
| 浏览器 / 前端 UI | Cookie 会话 + CSRF |
| **平台内部集成（本文重点）** | `X-DeerFlow-Internal-Token` + 可选 `X-DeerFlow-Owner-User-Id` |

### 1.1 Internal Token

```http
X-DeerFlow-Internal-Token: <DEER_FLOW_INTERNAL_AUTH_TOKEN>
```

- 值等于服务配置中的 `DEER_FLOW_INTERNAL_AUTH_TOKEN`（或 `config.yaml` 里对应项）
- 缺失或错误 → **401**

### 1.2 用户隔离

```http
X-DeerFlow-Owner-User-Id: zhangsan
```

- 多租户场景**必填**：Thread、上传目录、自定义 Agent 等按该 ID 隔离
- 数据目录示例：`.deer-flow/users/zhangsan/threads/{thread_id}/...`

### 1.3 环境变量示例

```bash
export GATEWAY="http://127.0.0.1:8001"
export INTERNAL_TOKEN="X-DeerFlow-Internal-Token-valid"   # 替换为真实 token
export OWNER="zhangsan"
```

---

## 2. Thread 生命周期

Thread 是对话会话单元，对应 LangGraph checkpoint 与 DeerFlow 元数据。

### 2.1 两种创建方式

**方式 A：显式创建（推荐列表页场景）**

```http
POST /api/threads
Content-Type: application/json
X-DeerFlow-Internal-Token: ...
X-DeerFlow-Owner-User-Id: zhangsan
```

```json
{
  "thread_id": "my-thread-001",
  "metadata": {
    "label": "部署助手",
    "source": "ops-platform"
  }
}
```

- `thread_id` 可选；不传则服务端生成 UUID
- `metadata` 写入 `thread_meta`，可用于业务归档（**不会**进 runs 表）

**方式 B：隐式创建（首条消息时自动建 Thread）**

调用 `POST /api/runs/stream` 且**不传** `config.configurable.thread_id` 时，Gateway 自动创建 Thread，并在响应头返回：

```http
Content-Location: /api/threads/{thread_id}/runs/{run_id}
```

首条 SSE 事件 `metadata` 也会带 `thread_id`、`run_id`。

### 2.2 获取 Thread 列表

```http
POST /api/threads/search
Content-Type: application/json
```

```json
{
  "limit": 20,
  "offset": 0,
  "metadata": {}
}
```

**响应**：Thread 数组，含 `thread_id`、`created_at`、`updated_at`、`metadata`、`title` 等。

> 仅通过 `runs/stream` 隐式创建且未写入 meta 的 Thread，可能不出现在 search 结果中；需要列表展示时建议先 `POST /api/threads`。

### 2.3 获取 / 更新 / 删除 Thread

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/threads/{thread_id}` | 元数据 |
| GET | `/api/threads/{thread_id}/state` | 完整图状态（messages、artifacts、thread_data） |
| PATCH | `/api/threads/{thread_id}` | 更新 metadata / title |
| DELETE | `/api/threads/{thread_id}` | 删除会话及关联数据 |

### 2.4 续聊

在后续 `POST /api/runs/stream` 请求体中设置：

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

LangGraph 兼容路径等价写法：`POST /api/langgraph/runs/stream`（经 Nginx 时走 `:2026`）。

---

## 3. 对话接口 `/api/runs/stream`

核心流式对话接口，返回 **SSE（Server-Sent Events）**。

```http
POST /api/runs/stream
Content-Type: application/json
Accept: text/event-stream
X-DeerFlow-Internal-Token: ...
X-DeerFlow-Owner-User-Id: zhangsan
```

### 3.1 请求头

| 参数 | 必填 | 说明 |
|------|------|------|
| `X-DeerFlow-Internal-Token` | 是 | Internal 认证 token |
| `Content-Type` | 是 | `application/json` |
| `X-DeerFlow-Owner-User-Id` | 视场景 | 多用户隔离时必填 |
| `Last-Event-ID` | 否 | SSE 断线重连，从该 event id 之后续传 |

### 3.2 请求体字段

| 参数 | 必填 | 说明 |
|------|------|------|
| `input` | 对话时必填 | 通常 `{"messages":[{"role":"human","content":"..."}]}` |
| `assistant_id` | 否 | 默认 `lead_agent`；自定义 Agent 填其 `name` |
| `context` | 否 | DeerFlow 扩展运行时上下文，合并到 `config.context`（见 3.4） |
| `config` | 否 | LangGraph RunnableConfig 覆盖项 |
| `metadata` | 否 | **写入 runs 表** `metadata_json` 的业务字段 |
| `multitask_strategy` | 否 | 同 thread 有进行中 run 时：`reject`（默认）/ `interrupt` / `rollback` |
| `stream_mode` | 否 | SSE 事件类型，默认 `values` |
| `stream_subgraphs` | 否 | 默认 `false`；`true` 包含子图事件 |
| `on_disconnect` | 否 | 默认 `cancel`；`continue` 适合后台任务 |
| `command` | 否 | LangGraph Command，HITL 恢复等场景 |

**当前未实现或部分未实现**：`enqueue`、`webhook`、`after_seconds`、`on_completion`、`if_not_exists`、`feedback_keys`。

### 3.3 config 常见子字段

| 子字段 | 说明 |
|--------|------|
| `config.configurable.thread_id` | 指定 Thread，续聊必填 |
| `config.configurable.checkpoint_ns` | 子 Agent checkpoint 命名空间 |
| `config.context` | 运行时 context（model、thinking 等） |
| `config.recursion_limit` | 图最大步数，默认 100，服务端有上限 |
| `config.tags` | LangSmith trace 标签 |
| `config.run_name` | LangSmith trace 名称 |
| `config.metadata` | 主要进 Langfuse/LangSmith trace |

### 3.4 context vs config vs metadata

```
HTTP 请求体
├── context（顶层）─────┐
├── metadata（顶层）───→ runs.metadata_json
└── config
    ├── recursion_limit / tags / run_name
    ├── configurable（thread_id 等）
    ├── context ───────→ 与顶层 context 合并
    └── metadata ──────→ trace 观测平台
```

**Worker** 指 Gateway 执行 run 的后台任务：准备 Agent、注入 callbacks、写 run 生命周期与 token 统计。

**Callbacks** 是挂在 run 上的观察者（LangChain 生命周期钩子）：

| Callback | 作用 |
|----------|------|
| `RunJournal` | 累加 token、写 runs / run_events |
| Langfuse Handler | 发送 trace 到 Langfuse |
| LangChainTracer | 发送到 LangSmith（若启用） |

**选型建议**：

| 目的 | 推荐字段 |
|------|----------|
| 换模型、开思考、开子 Agent | 顶层 `context` |
| 限制图步数、打 trace 标签 | `config` |
| 平台会话/渠道关联 ID | 顶层 `metadata`（进 DB） |
| trace 观测标签 | `config.metadata` |

**context 常用键**：`model_name`、`thinking_enabled`、`subagent_enabled`、`max_concurrent_subagents`、`max_total_subagents`、`agent_name`、`is_plan_mode`、`is_bootstrap`。

### 3.5 示例：无 Thread 首聊

```bash
curl -i -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{"input":{"messages":[{"role":"human","content":"你好,22+22=?"}]}}'
```

### 3.6 示例：带 Thread 续聊

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

### 3.7 SSE 事件

| event | 说明 |
|-------|------|
| `metadata` | 含 `run_id`、`thread_id` |
| `values` | 全量状态快照（messages、title、thread_data 等） |
| `messages-tuple` | 增量消息 |
| `updates` | 图状态更新 |
| `custom` | 自定义事件（如 subagent 进度） |
| `end` | 流结束 |

**thread_data** 示例：

```json
{
  "workspace_path": ".../threads/{id}/user-data/workspace",
  "uploads_path": ".../uploads",
  "outputs_path": ".../outputs"
}
```

Agent 内虚拟路径：`/mnt/user-data/workspace`、`/mnt/user-data/uploads`、`/mnt/user-data/outputs`。

### 3.8 同步等待（非 SSE）

```http
POST /api/runs/wait
```

请求体与 `/api/runs/stream` 相同，等待 run 结束后一次性返回最终状态（适合短任务、脚本集成）。

---

## 4. 人在回路 HITL

Agent 调用 `ask_clarification` 时会暂停，SSE 的 `values` 中出现 `human_input_request`；业务侧收集用户答案后，再发一条带 `human_input_response` 的消息继续执行。

### 4.1 识别待回复问题

在 `event: values` 的 messages 末尾查找 `type: "tool"`、`name: "ask_clarification"`：

```json
{
  "artifact": {
    "human_input": {
      "kind": "human_input_request",
      "request_id": "clarification:call_oDHaT50QQdGcBeuQ_MtcZQ",
      "question": "您使用的是哪种服务器？",
      "input_mode": "choice_with_other",
      "options": [
        {"id": "option-1", "label": "Linux", "value": "Linux"},
        {"id": "option-2", "label": "Windows", "value": "Windows"}
      ]
    }
  }
}
```

**务必保存最新的 `request_id`**。Agent 重新提问时会生成新的 `tool_call_id`，旧 ID 无效。

### 4.2 回复格式

```json
{
  "config": {"configurable": {"thread_id": "hitl-api-test-002"}},
  "input": {
    "messages": [{
      "role": "human",
      "content": "Windows",
      "additional_kwargs": {
        "hide_from_ui": true,
        "human_input_response": {
          "version": 1,
          "kind": "human_input_response",
          "source": "ask_clarification",
          "request_id": "clarification:call_oDHaT50QQdGcBeuQ_MtcZQ",
          "response_kind": "option",
          "option_id": "option-2",
          "value": "Windows"
        }
      }
    }]
  }
}
```

### 4.3 关键注意事项

1. **`content` 与 `value` 必须一致** — LLM 主要读 `content`；`content` 写「测试环境」而 `value` 写「Windows」会导致行为异常。
2. **`request_id` 必须对应当前 pending 问题**，不能用历史轮次的 ID。
3. **`option_id` 按 SSE 中 options 顺序**（`option-1`、`option-2`…）；后端不校验 `option_id` 与 `value` 是否匹配，集成层应自行保证一致。
4. 也可用 `response_kind: "text"` 自由文本回复，无需 `option_id`。
5. 多轮 HITL：每答一题 Agent 可能继续 `ask_clarification`，重复 4.1–4.2。

仓库内可复现脚本：`scripts/verify-api/test-human-in-the-loop.sh` 及 `hitl-step*.json`。

---

## 5. 自定义 Agent API

需在 `config.yaml` 启用：

```yaml
agents_api:
  enabled: true
```

Agent 存储于：`.deer-flow/users/{user_id}/agents/{name}/`（`SOUL.md` + `config.yaml`）。

### 5.1 创建 Agent

```http
POST /api/agents
```

```json
{
  "name": "zhangsan-agent",
  "description": "张三的技术顾问",
  "model": "chatling-plus",
  "tool_groups": ["web", "file:read"],
  "skills": [],
  "soul": "# SOUL.md\n\n你是专属技术顾问..."
}
```

### 5.2 列出 / 删除

```http
GET /api/agents
DELETE /api/agents/{name}
```

DELETE 若遇 307，加 `-L` 且 URL **不要** trailing slash。

### 5.3 使用自定义 Agent 对话

```json
{
  "assistant_id": "zhangsan-agent",
  "input": {"messages": [{"role": "human", "content": "你好"}]}
}
```

`tool_groups` 可选值见 `config.yaml` 的 `tool_groups`（如 `web`、`file:read`、`file:write`、`bash`）。

---

## 6. Skills 接入

Skills 是给 Agent 的**领域能力包**（Markdown 指令 + 可选脚本/资源），位于：

- `skills/public/` — 仓库内置，可提交 Git
- `skills/custom/` — 用户自定义，通常 gitignore

### 6.1 配置文件

根目录 `extensions_config.json`（从 `extensions_config.example.json` 复制）：

```json
{
  "skills": {
    "deep-research": {"enabled": true},
    "frontend-design": {"enabled": false}
  }
}
```

修改后需**重启 Gateway**，或调用 reload API（见 6.3）。

### 6.2 Skill 包结构

```
skills/public/deep-research/
├── SKILL.md          # 必需：YAML frontmatter + 指令正文
├── scripts/          # 可选
└── references/       # 可选
```

`SKILL.md` frontmatter 示例：

```yaml
---
name: deep-research
description: 需要系统性网络调研时使用此 skill
---
# Deep Research Skill
...
```

### 6.3 HTTP 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills` | 列出所有 skill |
| GET | `/api/skills/{name}` | 详情（含 content） |
| POST | `/api/skills/{name}/enable` | 启用 |
| POST | `/api/skills/{name}/disable` | 禁用 |
| POST | `/api/skills/install` | 上传 `.skill` 包安装到 custom |
| POST | `/api/skills/reload` | 进程内刷新缓存（需 admin 会话） |

Internal Token 集成通常直接改 `extensions_config.json`；UI 管理走 Cookie + admin。

### 6.4 在 Agent / 自定义 Agent 中启用

- 全局：在 `extensions_config.json` 设 `"enabled": true`
-  per-agent：`POST /api/agents` 的 `skills: ["deep-research"]`
- Agent 运行时通过 skill 工具按需加载 SKILL.md 内容

### 6.5 自定义 Skill 开发要点

1. `name` 与目录名一致，全局唯一
2. `description` 写清**何时触发**，Agent 靠它决定是否加载
3. 敏感操作在 `allowed_tools` 中声明（若 skill 元数据支持）
4. 勿与 MCP 文件工具重复操作同一 DeerFlow workspace

---

## 7. MCP 工具接入

MCP（Model Context Protocol）用于挂载外部工具服务（GitHub、数据库、HTTP API 等）。

### 7.1 配置位置

`extensions_config.json` → `mcpServers`：

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
    }
  }
}
```

### 7.2 传输类型

| type | 说明 |
|------|------|
| `stdio` | 本地子进程，常用 `npx` / `uvx` |
| `sse` | 远程 SSE MCP 服务 |
| `http` | 远程 HTTP MCP 服务，支持 OAuth |

`tool_call_timeout` 仅对 `stdio` 生效。

### 7.3 路由提示 routing

软引导模型优先选用某 MCP 工具（不禁止其他工具）：

```json
"routing": {
  "mode": "prefer",
  "priority": 50,
  "keywords": ["数据库", "SQL", "订单"]
}
```

### 7.4 HTTP 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mcp/config` | 查看配置（密钥脱敏） |
| PUT | `/api/mcp/config` | 更新配置 |
| POST | `/api/mcp/cache/reset` | 清空 MCP 工具缓存 |

### 7.5 接入步骤

1. `cp extensions_config.example.json extensions_config.json`
2. 添加 server 块，设 `"enabled": true`
3. 环境变量用 `$VAR` 引用，勿明文写密钥
4. 重启 Gateway 或 reset cache
5. 对话中 Agent 自动发现 MCP 工具（工具名带 `{server}_` 前缀）

### 7.6 注意事项

- **不要**为 DeerFlow workspace 再挂 filesystem MCP — 与内置文件工具路径语义冲突
- stdio 的 `command` 默认只允许 `npx`、`uvx`；可通过 `DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST` 扩展
- 详见 [backend/docs/MCP_SERVER.md](../backend/docs/MCP_SERVER.md)

---

## 8. 其他常用接口

### 8.1 模型列表

```http
GET /api/models
GET /api/models/{model_name}
```

### 8.2 文件上传

```http
POST /api/threads/{thread_id}/uploads
Content-Type: multipart/form-data
```

字段 `files` 支持 PDF / Office 等，自动转 Markdown 供 Agent 阅读。

```http
GET /api/threads/{thread_id}/uploads/list
```

### 8.3 取消 Run

```http
POST /api/threads/{thread_id}/runs/{run_id}/cancel
```

### 8.4 子 Agent

通过 `context` 开启：

```json
{
  "context": {
    "subagent_enabled": true,
    "max_concurrent_subagents": 2,
    "max_total_subagents": 10
  }
}
```

SSE `stream_subgraphs: true` 可观察子 Agent 进度。

### 8.5 计划模式

```json
{"context": {"is_plan_mode": true}}
```

启用 TodoList 中间件，适合多步骤任务。

### 8.6 定时任务（可选）

`config.yaml` 中 `scheduler.enabled: true` 时，可通过 Workspace UI `/workspace/scheduled-tasks` 管理；后台 run 设 `context.non_interactive: true`（仅 Internal 认证路径生效）。

### 8.7 LangGraph 兼容别名

| 兼容路径 | 原生路径 |
|----------|----------|
| `POST /api/langgraph/runs/stream` | `POST /api/runs/stream` |
| `POST /api/langgraph/threads` | `POST /api/threads` |
| `GET /api/langgraph/threads/{id}/state` | `GET /api/threads/{id}/state` |

---

## 9. 集成建议与排错

### 9.1 推荐集成流程

```
1. 配置 INTERNAL_TOKEN、OWNER
2. POST /api/threads（可选，便于列表展示）
3. POST /api/runs/stream（SSE 解析 metadata → 存 thread_id）
4. 循环：用户输入 → runs/stream（带 thread_id）
5. 若出现 ask_clarification → 解析 request_id → 构造 human_input_response → 再 stream
6. 需要文件时 → POST .../uploads → 在消息中引用虚拟路径
```

### 9.2 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 401 | Token 错误或缺失 |
| 同 thread 第二个 run 被拒绝 | 默认 `multitask_strategy: reject`；等上一个结束或设 `interrupt` |
| HITL 回复后 Agent 重复提问 | `request_id` 过期，或 `content`/`value` 不一致 |
| curl 多行 JSON 报错 | 用 `-d @file.json` 或脚本 |
| Agent API 404 | `agents_api.enabled` 未开 |
| Postgres 连接失败 | VPN / 改 SQLite / 检查 database 配置 |

### 9.3 仓库内验证脚本

| 脚本 | 用途 |
|------|------|
| `scripts/verify-api/test-human-in-the-loop.sh` | HITL 多步流程 |
| `scripts/verify-api/test-custom-agent-api.sh` | 自定义 Agent |
| `scripts/verify-api/test-subagent-stream.sh` | 子 Agent 并行 |

### 9.4 延伸阅读

- [backend/docs/API.md](../backend/docs/API.md) — 完整 API 参考
- [backend/docs/MCP_SERVER.md](../backend/docs/MCP_SERVER.md) — MCP 详细配置
- [AGENTS.md](../AGENTS.md) — 仓库架构与模块导航
- [Install.md](../Install.md) — 安装与 `make dev` 启动

---

## 附录：RunCreateRequest 字段速查

完整类型定义见 `backend/app/gateway/routers/thread_runs.py` 中 `RunCreateRequest`。

**已实现且常用**：`input`、`assistant_id`、`context`、`config`、`metadata`、`multitask_strategy`、`stream_mode`、`stream_subgraphs`、`on_disconnect`、`command`、`checkpoint_id`、`interrupt_before`、`interrupt_after`。

**DeerFlow 特有行为摘要**：

- 顶层 `context` 通过 `merge_run_context_overrides` 合并进 `config.context` / `configurable`（已有键不被覆盖）
- 顶层 `metadata` 写入 **runs 表**；`config.metadata` 主要服务 trace
- Worker 注入 Langfuse session/user/tags 到 trace metadata
- `on_disconnect: continue` 适合集成侧短连接、长任务后台跑完

---

*文档版本：与 deer-flow 主分支同步编写。接口以 Gateway 源码为准，升级后请以 `backend/docs/API.md` 核对。*
