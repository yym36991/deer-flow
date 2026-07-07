"""美事回调配置（从 config.yaml 的 ``meishi`` 段加载）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deerflow.config.app_config import AppConfig, get_app_config


@dataclass
class MeishiWelcomeCmd:
    text: str
    cmd: str
    action_type: str = "backInputbox"
    open_url: str | None = None


@dataclass
class MeishiConfig:
    enabled: bool = False
    app_id: str = ""
    secret: str = ""
    langgraph_url: str = "http://localhost:8001/api"
    assistant_id: str = "lead_agent"
    require_sign: bool = True
    require_token: bool = False
    token_validate_url: str = "https://openapi-meishi.58v5.cn/login/checkUserTokenByUsername"
    token_validate_timeout_seconds: float = 5.0
    pre_qa_prefix_user_oa: bool = False
    pre_qa_scalar_map: dict[str, list[str]] = field(default_factory=dict)
    welcome_text: str = "你好，我是 DeerFlow 云端助手，有什么可以帮你？"
    welcome_cmd_list: list[MeishiWelcomeCmd] = field(default_factory=list)
    stream_ack_message: str = "已收到您的问题，正在处理中…"
    button_default_answer: str = "操作已收到。"
    context: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _parse_welcome_cmds(raw: Any) -> list[MeishiWelcomeCmd]:
    if not isinstance(raw, list):
        return []
    cmds: list[MeishiWelcomeCmd] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        cmd = item.get("cmd")
        if not isinstance(text, str) or not isinstance(cmd, str):
            continue
        cmds.append(
            MeishiWelcomeCmd(
                text=text,
                cmd=cmd,
                action_type=str(item.get("action_type") or item.get("actionType") or "backInputbox"),
                open_url=item.get("open_url") or item.get("openUrl"),
            )
        )
    return cmds


def load_meishi_config(app_config: AppConfig | None = None) -> MeishiConfig:
    """从 AppConfig.extra['meishi'] 解析美事配置。"""
    cfg = app_config or get_app_config()
    raw = _as_dict(cfg.model_extra.get("meishi") if cfg.model_extra else None)
    if not raw and hasattr(cfg, "meishi"):
        raw = _as_dict(getattr(cfg, "meishi", None))

    channels = _as_dict(cfg.model_extra.get("channels") if cfg.model_extra else None)
    default_langgraph = channels.get("langgraph_url") or "http://localhost:8001/api"

    welcome_cmds = _parse_welcome_cmds(raw.get("welcome_cmd_list") or raw.get("cmd_list"))
    if not welcome_cmds:
        welcome_cmds = [
            MeishiWelcomeCmd(text="帮我总结今天的工作", cmd="帮我总结今天的工作", action_type="sendMsg"),
            MeishiWelcomeCmd(text="查看使用说明", cmd="DeerFlow 有哪些能力？", action_type="sendMsg"),
        ]

    scalar_raw = raw.get("pre_qa_scalar_map") or raw.get("scalar_map") or {}
    scalar_map: dict[str, list[str]] = {}
    if isinstance(scalar_raw, dict):
        for key, val in scalar_raw.items():
            if isinstance(key, str) and isinstance(val, list):
                scalar_map[key] = [str(v) for v in val]

    token_cfg = _as_dict(raw.get("token_validation"))

    return MeishiConfig(
        enabled=bool(raw.get("enabled", False)),
        app_id=str(raw.get("app_id") or raw.get("appId") or ""),
        secret=str(raw.get("secret") or ""),
        langgraph_url=str(raw.get("langgraph_url") or default_langgraph),
        assistant_id=str(raw.get("assistant_id") or "lead_agent"),
        require_sign=bool(raw.get("require_sign", True)),
        require_token=bool(raw.get("require_token") or token_cfg.get("enabled")),
        token_validate_url=str(raw.get("token_validate_url") or token_cfg.get("url") or "https://openapi-meishi.58v5.cn/login/checkUserTokenByUsername"),
        token_validate_timeout_seconds=float(raw.get("token_validate_timeout_seconds") or token_cfg.get("timeout_seconds") or 5.0),
        pre_qa_prefix_user_oa=bool(raw.get("pre_qa_prefix_user_oa", False)),
        pre_qa_scalar_map=scalar_map,
        welcome_text=str(raw.get("welcome_text") or "你好，我是 DeerFlow 云端助手，有什么可以帮你？"),
        welcome_cmd_list=welcome_cmds,
        stream_ack_message=str(raw.get("stream_ack_message") or "已收到您的问题，正在处理中…"),
        button_default_answer=str(raw.get("button_default_answer") or "操作已收到。"),
        context=_as_dict(raw.get("context")),
        config=_as_dict(raw.get("config")),
    )
