#!/usr/bin/env python3
"""
DeerFlow API 手动验证。

推荐通过 verify.sh 运行:
  bash scripts/verify-api/verify.sh api_verify.py register
  bash scripts/verify-api/verify.sh api_verify.py create-thread
  bash scripts/verify-api/verify.sh api_verify.py chat

一键流程:
  bash scripts/verify-api/run-verify.sh

子命令:
  init-admin | register | login | me
  create-thread | chat | chat-stream
  search-threads | list-runs | inspect-db
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import VERIFY_DIR, load_postgres_url  # noqa: E402

# =============================================================================
# 可修改区域
# =============================================================================
CONFIG: dict[str, Any] = {
    "base_url": "http://127.0.0.1:8001",
    "email": "user_a@example.com",
    "password": "UserAPass123!",
    "cookie_file": ".deer-flow/verify-api/user_a.cookies",
    "thread_id": "",
    "message": "1+2等于多少？只回答数字",
    "model_name": "deepseek-chat",
    "thread_metadata": {"label": "api-verify"},
    "admin_email": "admin@example.com",
    "admin_password": "AdminPass123!",
}

ROOT = Path(__file__).resolve().parents[2]


def _session_key() -> str:
    return Path(CONFIG["cookie_file"]).stem


def _state_path() -> Path:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    return VERIFY_DIR / f"{_session_key()}.state.json"


def _load_state() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _save_state(**updates: Any) -> dict[str, Any]:
    state = _load_state()
    state.update({k: v for k, v in updates.items() if v is not None})
    _state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def _cookie_path() -> Path:
    p = ROOT / CONFIG["cookie_file"]
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_cookies() -> dict[str, str]:
    path = _cookie_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _save_cookies(cookies: dict[str, str]) -> None:
    _cookie_path().write_text(json.dumps(cookies, indent=2), encoding="utf-8")


def _merge_set_cookies(existing: dict[str, str], headers: Any) -> dict[str, str]:
    out = dict(existing)
    for header in headers.get_all("Set-Cookie") or []:
        part = header.split(";", 1)[0]
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _resolve_thread_id(args: argparse.Namespace | None = None) -> str:
    if args and getattr(args, "thread_id", ""):
        return args.thread_id.strip()
    if CONFIG.get("thread_id"):
        return str(CONFIG["thread_id"]).strip()
    return str(_load_state().get("thread_id") or "").strip()


def _request_headers_as_dict(req: urllib.request.Request) -> dict[str, str]:
    return {k: v for k, v in req.header_items()}


def _response_headers_as_dict(headers: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key in headers:
        values = headers.get_all(key)
        out[key] = values if values else [headers[key]]
    return out


def _format_body_for_log(data: bytes | None, content_type: str) -> str:
    if not data:
        return "(空)"
    text = data.decode(errors="replace")
    if "json" in content_type:
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return text
    return text


def _log_http_exchange(
    *,
    method: str,
    url: str,
    request_headers: dict[str, str],
    request_body: bytes | None,
    content_type: str,
    status: int,
    response_headers: dict[str, list[str]],
    response_body: str,
    streamed: bool = False,
) -> None:
    sep = "=" * 72
    print(sep)
    print(f">>> 请求: {method} {url}")
    print("--- 请求头 ---")
    print(json.dumps(request_headers, ensure_ascii=False, indent=2))
    print("--- 请求体 ---")
    print(_format_body_for_log(request_body, content_type))
    print(f"<<< 响应: HTTP {status}")
    print("--- 响应头 ---")
    print(json.dumps(response_headers, ensure_ascii=False, indent=2))
    print("--- 响应体 ---")
    if streamed:
        print("(流式响应，正文见下方实时输出)")
    else:
        if response_body:
            try:
                print(json.dumps(json.loads(response_body), ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                print(response_body)
        else:
            print("(空)")
    print(sep)
    print()


def _request(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    form: dict[str, str] | None = None,
    need_csrf: bool = False,
    stream: bool = False,
    timeout: float = 300,
) -> Any:
    base = CONFIG["base_url"].rstrip("/")
    url = base + path
    cookies = _load_cookies()
    if form is not None:
        content_type = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode()
    elif body is not None:
        content_type = "application/json"
        data = json.dumps(body).encode()
    else:
        content_type = "application/json"
        data = None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", content_type)
    if cookies:
        req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))
    if need_csrf and cookies.get("csrf_token"):
        req.add_header("X-CSRF-Token", cookies["csrf_token"])
    request_headers = _request_headers_as_dict(req)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        _log_http_exchange(
            method=method,
            url=url,
            request_headers=request_headers,
            request_body=data,
            content_type=content_type,
            status=e.code,
            response_headers=_response_headers_as_dict(e.headers),
            response_body=body_text,
        )
        if e.code == 400 and "email_already_exists" in body_text:
            print("提示: 邮箱已存在，可执行 login 或先 clear-database.py --yes", file=sys.stderr)
        sys.exit(1)
    new = _merge_set_cookies(cookies, resp.headers)
    if new != cookies:
        _save_cookies(new)
    if stream:
        _log_http_exchange(
            method=method,
            url=url,
            request_headers=request_headers,
            request_body=data,
            content_type=content_type,
            status=resp.status,
            response_headers=_response_headers_as_dict(resp.headers),
            response_body="",
            streamed=True,
        )
        return resp
    raw = resp.read().decode()
    _log_http_exchange(
        method=method,
        url=url,
        request_headers=request_headers,
        request_body=data,
        content_type=content_type,
        status=resp.status,
        response_headers=_response_headers_as_dict(resp.headers),
        response_body=raw,
    )
    return json.loads(raw) if raw else {}


def _pretty(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _run_body(message: str) -> dict:
    return {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "user", "content": message}]},
        "context": {
            "model_name": CONFIG["model_name"],
            "thinking_enabled": False,
            "subagent_enabled": False,
        },
        "config": {"recursion_limit": 25},
    }


def cmd_init_admin(_: argparse.Namespace) -> None:
    r = _request(
        "POST",
        "/api/v1/auth/initialize",
        body={"email": CONFIG["admin_email"], "password": CONFIG["admin_password"]},
    )
    print("管理员 user_id =", r.get("id"))
    _save_state(user_id=r.get("id"), email=CONFIG["admin_email"], role="admin")


def cmd_register(_: argparse.Namespace) -> None:
    r = _request(
        "POST",
        "/api/v1/auth/register",
        body={"email": CONFIG["email"], "password": CONFIG["password"]},
        need_csrf=True,
    )
    uid = r.get("id")
    print("注册成功 user_id =", uid)
    _save_state(user_id=uid, email=CONFIG["email"], role=r.get("system_role"), thread_id="")


def cmd_login(_: argparse.Namespace) -> None:
    _request(
        "POST",
        "/api/v1/auth/login/local",
        form={"username": CONFIG["email"], "password": CONFIG["password"]},
        timeout=60,
    )
    print("登录成功")


def cmd_me(_: argparse.Namespace) -> None:
    r = _request("GET", "/api/v1/auth/me")
    print("当前 user_id =", r.get("id"))
    _save_state(user_id=r.get("id"), email=r.get("email"))


def cmd_create_thread(args: argparse.Namespace) -> None:
    tid = _resolve_thread_id(args) or str(uuid.uuid4())
    if not _resolve_thread_id(args) and not CONFIG.get("thread_id"):
        print(f"自动生成 thread_id: {tid}")
    r = _request(
        "POST",
        "/api/threads",
        body={"thread_id": tid, "metadata": CONFIG["thread_metadata"]},
        need_csrf=True,
    )
    _save_state(thread_id=tid)
    print(f"thread_id 已保存到 {_state_path()}")
    print(f"thread_id = {tid}")


def cmd_chat(args: argparse.Namespace) -> None:
    tid = _resolve_thread_id(args)
    if not tid:
        print(
            "错误: 无 thread_id。请先 create-thread，或在 CONFIG / --thread-id 中指定",
            file=sys.stderr,
        )
        sys.exit(1)
    msg = args.message or CONFIG["message"]
    print(f"thread_id={tid}\nmessage={msg}")
    r = _request(
        "POST",
        f"/api/threads/{tid}/runs/wait",
        body=_run_body(msg),
        need_csrf=True,
        timeout=600,
    )
    msgs = r.get("messages") or []
    if msgs:
        print("\n--- 助手回复 ---")
        print(msgs[-1].get("content", msgs[-1]))


def cmd_chat_stream(args: argparse.Namespace) -> None:
    tid = _resolve_thread_id(args)
    if not tid:
        sys.exit("需要 thread_id，请先 create-thread")
    msg = args.message or CONFIG["message"]
    resp = _request(
        "POST",
        f"/api/threads/{tid}/runs/stream",
        body={**_run_body(msg), "stream_mode": ["values"]},
        need_csrf=True,
        stream=True,
        timeout=600,
    )
    try:
        print("--- 响应体 (stream) ---")
        while chunk := resp.read(4096):
            print(chunk.decode(errors="replace"), end="", flush=True)
    finally:
        resp.close()
    print()


def cmd_search_threads(_: argparse.Namespace) -> None:
    r = _request("POST", "/api/threads/search", body={"limit": 50}, need_csrf=True)
    print(f"共 {len(r)} 个 thread")


def cmd_list_runs(args: argparse.Namespace) -> None:
    tid = _resolve_thread_id(args)
    if not tid:
        sys.exit("需要 thread_id")
    _request("GET", f"/api/threads/{tid}/runs", need_csrf=True)


def cmd_inspect_db(_: argparse.Namespace) -> None:
    try:
        import sqlalchemy as sa
    except ImportError:
        print("错误: 需要 sqlalchemy。请用: bash scripts/verify-api/verify.sh api_verify.py inspect-db", file=sys.stderr)
        sys.exit(1)

    print("=" * 72)
    print("inspect-db 直连 PostgreSQL，不经过 Gateway HTTP，无请求/响应头。")
    print("=" * 72)
    print()

    state = _load_state()
    if state:
        print("--- 本地会话状态 ---")
        _pretty(state)
        print()

    engine = sa.create_engine(load_postgres_url())

    def q(sql: str, **p: Any) -> list[dict]:
        with engine.connect() as c:
            return [dict(r) for r in c.execute(sa.text(sql), p).mappings().all()]

    tables = [r["tablename"] for r in q("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]

    print("=== users ===")
    rows = q("SELECT id, email, system_role, created_at FROM users ORDER BY created_at")
    print(rows if rows else "(空表)")

    print("\n=== threads_meta ===")
    rows = q(
        "SELECT thread_id, user_id, status, metadata_json, created_at FROM threads_meta ORDER BY created_at"
    )
    print(rows if rows else "(空表)")

    print("\n=== channel_mappings ===")
    if "channel_mappings" in tables:
        rows = q("SELECT * FROM channel_mappings ORDER BY created_at LIMIT 20")
        print(rows if rows else "(空表 — Web API 路径通常不写此表)")
    else:
        print("(本分支无此表 — 仅 IM/美事绑定；Web API 不涉及)")

    print("\n=== runs (最近 10) ===")
    rows = q(
        "SELECT run_id, thread_id, user_id, status, created_at FROM runs ORDER BY created_at DESC LIMIT 10"
    )
    print(rows if rows else "(空表)")

    print("\n=== run_events 样例 ===")
    runs = q("SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 3")
    if not runs:
        print("(无数据)")
    for run in runs:
        rid = run["run_id"]
        print(f"-- {rid}")
        for e in q(
            "SELECT seq, event_type, left(content,100) AS preview FROM run_events WHERE run_id=:r ORDER BY seq LIMIT 2",
            r=rid,
        ):
            print("  ", e)


def main() -> None:
    p = argparse.ArgumentParser(description="DeerFlow API 验证")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in [
        ("init-admin", "初始化管理员（可选）"),
        ("register", "注册并登录"),
        ("login", "登录已有账号"),
        ("me", "查看 user_id"),
        ("search-threads", "列出 threads"),
        ("inspect-db", "查库"),
    ]:
        sub.add_parser(name, help=help_)
    ct = sub.add_parser("create-thread", help="创建 thread（自动保存 thread_id）")
    ct.add_argument("--thread-id", default="", help="指定 thread_id，默认自动生成")
    for name in ("chat", "chat-stream"):
        sp = sub.add_parser(name, help="对话（自动读取已保存的 thread_id）")
        sp.add_argument("--thread-id", default="")
        sp.add_argument("-m", "--message", default="")
    lr = sub.add_parser("list-runs")
    lr.add_argument("--thread-id", default="")
    args = p.parse_args()
    {
        "init-admin": cmd_init_admin,
        "register": cmd_register,
        "login": cmd_login,
        "me": cmd_me,
        "create-thread": cmd_create_thread,
        "chat": cmd_chat,
        "chat-stream": cmd_chat_stream,
        "search-threads": cmd_search_threads,
        "list-runs": cmd_list_runs,
        "inspect-db": cmd_inspect_db,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
