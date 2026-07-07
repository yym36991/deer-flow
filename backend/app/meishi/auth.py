"""美事回调鉴权：密钥签名校验与可选 token 校验。"""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any

import httpx

from app.meishi.config import MeishiConfig
from app.meishi.schemas import MeishiCommonParams

logger = logging.getLogger(__name__)


class MeishiAuthError(Exception):
    """鉴权失败。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def compute_sign(timestamp: str, secret: str, random: str) -> str:
    """计算美事约定的 MD5 签名：md5(timestamp + secret + random)。"""
    payload = f"{timestamp}{secret}{random}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def verify_sign(params: MeishiCommonParams, secret: str) -> bool:
    if not secret:
        return False
    if not params.sign_str or not params.timestamp or not params.random:
        return False
    expected = compute_sign(params.timestamp, secret, params.random)
    return secrets.compare_digest(expected, params.sign_str)


async def verify_token(params: MeishiCommonParams, config: MeishiConfig) -> bool:
    """调用美事 OpenAPI 校验用户 token（可选）。"""
    if not params.token or not params.user_oa:
        return False

    url = config.token_validate_url
    timeout = config.token_validate_timeout_seconds
    body = {"username": params.user_oa, "token": params.token}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("Meishi token validation request failed for userOa=%s", params.user_oa)
        return False

    return _token_response_ok(data)


def _token_response_ok(data: Any) -> bool:
    """解析 OpenAPI 返回，兼容常见成功字段。"""
    if not isinstance(data, dict):
        return False
    code = data.get("code")
    if code in (1, 200, "1", "200"):
        return True
    if data.get("success") is True:
        return True
    inner = data.get("data")
    if isinstance(inner, dict) and inner.get("valid") is True:
        return True
    return False


async def authenticate_callback(params: MeishiCommonParams, config: MeishiConfig) -> None:
    """校验回调请求；失败时抛出 :class:`MeishiAuthError`。"""
    if config.require_sign:
        if not verify_sign(params, config.secret):
            raise MeishiAuthError("signStr 校验失败")

    if config.require_token:
        if not await verify_token(params, config):
            raise MeishiAuthError("token 校验失败")
