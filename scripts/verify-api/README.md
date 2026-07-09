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

## config.yaml 要点

- `models`: 仅 `deepseek-chat`
- `database`: postgres + 你的连接串
- `run_events.backend`: `db`

`start-gateway.sh` 会强制 `DEER_FLOW_CONFIG_PATH` 指向项目根 `config.yaml`。
