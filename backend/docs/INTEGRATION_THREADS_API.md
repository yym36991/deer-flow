# DeerFlow Integration API — 创建 Thread（JIT 用户 + 会话）

**方法：** HTTP POST

**接口：** `{GATEWAY_BASE_URL}/api/v1/integration/threads`

**数据类型：** JSON 格式

**Content-Type：** `application/json`

---

## 设计原则（与 register / create-thread 对齐）

| 部分 | 行为 |
|------|------|
| **响应 Body** | 与 `POST /api/threads` 完全一致（`ThreadResponse`） |
| **响应 Set-Cookie** | 与 `POST /api/v1/auth/register` 一致：`access_token` + `csrf_token` 只在 Cookie 里，**不在 JSON body 返回** |

---

## 认证说明

| 方式 | 传参 |
|------|------|
| 密码登录 / 新会话 | body：`username` + `password` |
| 已有会话 | Cookie：`access_token=…` |

---

## 请求 Body 字段说明

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| username | String | 条件必填 | | 企业用户名，映射 `{username}@58.com` |
| password | String | 条件必填 | | 集成方保管密码，≥8 位 |
| thread_id | String | 否 | 自动 UUID | 自定义 thread id |
| assistant_id | String | 否 | | 关联 assistant |
| metadata | Object | 否 | `{}` | 自定义元数据 |

---

## 响应 Body 字段说明（= POST /api/threads）

| 字段 | 类型 | 说明 |
|------|------|------|
| thread_id | String | thread 唯一标识 |
| status | String | 默认 `idle` |
| created_at | String | ISO 8601 |
| updated_at | String | ISO 8601 |
| metadata | Object | thread 元数据 |
| values | Object | 新建为 `{}` |
| interrupts | Object | 新建为 `{}` |

---

## 响应 Set-Cookie（不在 Body 里）

| Cookie | 何时设置 | 说明 |
|--------|----------|------|
| access_token | 密码路径（新会话） | HttpOnly JWT，与 register 一致 |
| csrf_token | 每次成功 POST | CSRF middleware 设置，与 register 一致 |

后续 POST/PUT/DELETE/PATCH 需：Cookie（`access_token` + `csrf_token`）+ Header `X-CSRF-Token: <csrf_token cookie 值>`。

---

## curl 示例

```shell
# 1. 首次 JIT（-c 保存 cookie）
curl -i -X POST "http://127.0.0.1:8001/api/v1/integration/threads" \
  -H "Content-Type: application/json" \
  -c /tmp/deerflow.cookies.txt \
  -d '{"username":"zhangsan","password":"Integr8Pass!","metadata":{"source":"my-app"}}'

# 2. Cookie 开新 thread
curl -i -X POST "http://127.0.0.1:8001/api/v1/integration/threads" \
  -H "Content-Type: application/json" \
  -b /tmp/deerflow.cookies.txt \
  -c /tmp/deerflow.cookies.txt \
  -d '{}'

# 3. 流式对话
CSRF=$(grep csrf_token /tmp/deerflow.cookies.txt | awk '{print $NF}')
curl -N -X POST "http://127.0.0.1:8001/api/threads/<thread_id>/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -b /tmp/deerflow.cookies.txt \
  -d '{"assistant_id":"lead_agent","input":{"messages":[{"role":"user","content":"你好"}]}}'
```
