# DeerFlow API 本地验证

## 推荐命令（用 verify.sh，不依赖系统 python）

**终端 1 — 启动 Gateway**

```bash
bash scripts/verify-api/start-gateway.sh
```

**终端 2 — 单步验证**

```bash
bash scripts/verify-api/verify.sh clear-database.py --yes
bash scripts/verify-api/verify.sh api_verify.py register
bash scripts/verify-api/verify.sh api_verify.py create-thread
bash scripts/verify-api/verify.sh api_verify.py chat
bash scripts/verify-api/verify.sh api_verify.py inspect-db
```

**或一键跑通**

```bash
bash scripts/verify-api/run-verify.sh
# 含 admin: bash scripts/verify-api/run-verify.sh --init-admin
# 自定义问题: bash scripts/verify-api/run-verify.sh -m "用一句话介绍北京"
```

> 不要用 `python`（macOS 常未安装）。若坚持用 python3 跑 inspect-db/clear-database，需自行安装 sqlalchemy；**推荐始终用 verify.sh**。

---

## 改进说明

| 功能 | 说明 |
|------|------|
| `verify.sh` | 通过 `backend` 的 `uv run` 执行脚本，依赖齐全 |
| `thread_id` 自动保存 | `create-thread` 后写入 `.deer-flow/verify-api/<用户>.state.json`，`chat` 自动读取，**无需手改 CONFIG** |
| `clear-database.py` | 清库时同时删除本地 cookie/state |
| `init-admin` | **可选**；API 验证可直接 `register` |
| `run-verify.sh` | 串联清库 → 注册 → 建 thread → 对话 → 查库 |

---

## 两用户验证（user_a 1 thread，user_b 2 thread）

编辑 `api_verify.py` 顶部 `CONFIG`，然后：

**用户 A**

```bash
bash scripts/verify-api/verify.sh api_verify.py register
bash scripts/verify-api/verify.sh api_verify.py create-thread
bash scripts/verify-api/verify.sh api_verify.py chat
```

**用户 B** — 改 `email` / `password` / `cookie_file` 为 `user_b`，再：

```bash
bash scripts/verify-api/verify.sh api_verify.py register
bash scripts/verify-api/verify.sh api_verify.py create-thread   # thread 1
bash scripts/verify-api/verify.sh api_verify.py chat
bash scripts/verify-api/verify.sh api_verify.py create-thread   # thread 2（自动新 UUID）
bash scripts/verify-api/verify.sh api_verify.py chat
bash scripts/verify-api/verify.sh api_verify.py inspect-db
```

换消息：改 `CONFIG["message"]` 或 `chat -m "新问题"`。

---

## Integration API（`POST /api/v1/integration/threads`）

业务方集成入口：JIT 创建 `{username}@58.com` 用户、签发 JWT、创建 thread。无 `integration/session`；token 过期后用 `username+password` 重新调用即可换票并开新 thread。

### 认证方式（二选一）

| 方式 | 传参位置 |
|------|----------|
| 密码登录 / 新会话 | JSON body：`username` + `password`（必须同时提供） |
| 已有会话 | `Cookie: access_token=…`（**不在 body 里传 token**） |

### 请求场景

| 场景 | 行为 |
|------|------|
| 只传 `username` + `password` | JIT 用户 → 签发 JWT → 建 thread，返回 thread + token |
| 只传有效 token | 按 token 用户建 thread，**不**重新发 token |
| 只传过期/无效 token | 401，不建 thread |
| 同时传 `username+password` 和任意 token | 验密 → **新** JWT → **新** thread |
| 既无 token 又无密码 | 401 |

### Body 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `username` | 密码路径必填 | 企业用户名（不含 `@58.com`） |
| `password` | 密码路径必填 | 集成方保管，≥8 位且非弱密码 |
| `thread_id` | 否 | 自定义 thread id，默认 UUID |
| `assistant_id` | 否 | 关联 assistant |
| `metadata` | 否 | 自定义元数据 |

### 响应

**Body** 与 `POST /api/threads` 完全一致（`thread_id`、`status`、`created_at`、`updated_at`、`metadata`、`values`、`interrupts`）。

**Set-Cookie**（与 register 一致，不在 body 里返回 token）：

| Cookie | 何时设置 |
|--------|----------|
| `access_token` | 密码路径（新会话） |
| `csrf_token` | 每次成功 POST（CSRF middleware） |

后续写操作需 Cookie + `X-CSRF-Token` 头（值与 `csrf_token` cookie 相同）。

### curl 示例

**1. 首次接入（JIT + 拿 cookie）**

```bash
curl -sS -X POST 'http://127.0.0.1:8001/api/v1/integration/threads' \
  -H 'Content-Type: application/json' \
  -c /tmp/deerflow.cookies.txt \
  -d '{"username":"zhangsan","password":"Integr8Pass!","metadata":{"source":"my-app"}}'
```

**2. Cookie 开新 thread**

```bash
curl -sS -X POST 'http://127.0.0.1:8001/api/v1/integration/threads' \
  -H 'Content-Type: application/json' \
  -b /tmp/deerflow.cookies.txt \
  -c /tmp/deerflow.cookies.txt \
  -d '{}'
```

**3. 流式对话（需 CSRF）**

```bash
CSRF=$(grep csrf_token /tmp/deerflow.cookies.txt | awk '{print $NF}')
curl -sS -N -X POST "http://127.0.0.1:8001/api/threads/<thread_id>/runs/stream" \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" \
  -b /tmp/deerflow.cookies.txt \
  -d '{"assistant_id":"lead_agent","input":{"messages":[{"role":"user","content":"你好"}]}}'
```

### verify.sh 快捷命令

```bash
bash scripts/verify-api/verify.sh api_verify.py integration-create-thread
bash scripts/verify-api/verify.sh api_verify.py integration-stream
```

---

## config.yaml 要点

- `models`: 仅 `deepseek-chat`
- `database`: postgres + 你的连接串
- `run_events.backend`: `db`

`start-gateway.sh` 会强制 `DEER_FLOW_CONFIG_PATH` 指向项目根 `config.yaml`。
