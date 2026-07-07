"""Tests for Meishi (美事) callback integration."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.gateway.app import create_app
from app.meishi.auth import compute_sign, verify_sign
from app.meishi.config import MeishiConfig, MeishiWelcomeCmd
from app.meishi.schemas import MeishiApiResponse, MeishiCommonParams
from app.meishi.service import MeishiAgentService
from app.meishi.sse import format_meishi_sse_chunk, format_meishi_sse_done


def _sign_body(secret: str, body: dict) -> dict:
    body = dict(body)
    body.setdefault("timestamp", "1657001374060")
    body.setdefault("random", "543009")
    body["signStr"] = compute_sign(body["timestamp"], secret, body["random"])
    return body


@pytest.fixture
def meishi_config() -> MeishiConfig:
    return MeishiConfig(
        enabled=True,
        secret="test-secret",
        require_sign=True,
        require_token=False,
        welcome_text="欢迎",
        welcome_cmd_list=[MeishiWelcomeCmd(text="你好", cmd="你好", action_type="sendMsg")],
    )


class TestMeishiSign:
    def test_compute_sign_matches_spec_example(self):
        expected = hashlib.md5(b"1657001374060test-secret543009").hexdigest()
        assert compute_sign("1657001374060", "test-secret", "543009") == expected

    def test_verify_sign(self):
        params = MeishiCommonParams(
            signStr=compute_sign("1", "sec", "r"),
            timestamp="1",
            random="r",
        )
        assert verify_sign(params, "sec") is True
        assert verify_sign(params, "wrong") is False


class TestMeishiService:
    @pytest.mark.asyncio
    async def test_pre_qa_prefix_oa(self, meishi_config: MeishiConfig):
        meishi_config.pre_qa_prefix_user_oa = True
        service = MeishiAgentService(config=meishi_config)
        from app.meishi.schemas import PreQARequest

        resp = await service.handle_pre_qa(PreQARequest(user_oa="zhangsan", msg="你好", sign_str="", timestamp="", random=""))
        assert resp.code == 1
        assert resp.data["modifyMsg"] == "[用户 zhangsan] 你好"

    @pytest.mark.asyncio
    async def test_welcome(self, meishi_config: MeishiConfig):
        service = MeishiAgentService(config=meishi_config)
        from app.meishi.schemas import WelcomeRequest

        resp = await service.handle_welcome(WelcomeRequest(user_oa="zhangsan"))
        assert resp.code == 1
        assert resp.data["welcomeText"] == "欢迎"
        assert len(resp.data["cmdList"]) == 1

    @pytest.mark.asyncio
    async def test_message_sync(self, meishi_config: MeishiConfig):
        service = MeishiAgentService(config=meishi_config)
        from app.meishi.schemas import MessageSyncRequest

        resp = await service.handle_message_sync(MessageSyncRequest(type="MIS:ImageMsg", msg_id="1", user_oa="zhangsan"))
        assert resp.code == 1
        assert resp.data == {}


class TestMeishiRouter:
    @pytest.fixture
    def client(self, meishi_config: MeishiConfig):
        with patch("app.gateway.routers.meishi.load_meishi_config", return_value=meishi_config):
            with patch("app.meishi.service.load_meishi_config", return_value=meishi_config):
                app = create_app()
                with TestClient(app) as test_client:
                    yield test_client

    def test_health(self, client: TestClient):
        resp = client.get("/api/meishi/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["enabled"] is True
        assert "charset=utf-8" in resp.headers.get("content-type", "").lower()

    def test_in_qa_blocking_json_utf8(self, client: TestClient, meishi_config: MeishiConfig):
        """美事非流式路径：JSON data.answer，须带 charset=utf-8。"""
        mock_service = MagicMock()
        mock_service.handle_in_qa_blocking = AsyncMock(
            return_value=MeishiApiResponse(
                code=1,
                msg="",
                data={"answer": "今天是2026年6月4日，星期四。"},
            )
        )
        body = _sign_body(
            meishi_config.secret,
            {"userOa": "zhangsan", "msg": "今天几月几号？", "senderId": "s1", "toId": "t1"},
        )
        with patch("app.gateway.routers.meishi.get_meishi_service", return_value=mock_service):
            resp = client.post(
                "/api/meishi/callback/qa",
                json=body,
                headers={"Accept": "application/json"},
            )
        assert resp.status_code == 200
        assert "charset=utf-8" in resp.headers.get("content-type", "").lower()
        assert resp.json()["data"]["answer"] == "今天是2026年6月4日，星期四。"
        assert "ä»" not in resp.text

    def test_pre_qa_requires_sign(self, client: TestClient, meishi_config: MeishiConfig):
        body = {"userOa": "zhangsan", "msg": "hi"}
        resp = client.post("/api/meishi/callback/pre-qa", json=body)
        assert resp.status_code == 403

        signed = _sign_body(meishi_config.secret, body)
        resp = client.post("/api/meishi/callback/pre-qa", json=signed)
        assert resp.status_code == 200
        assert resp.json()["code"] == 1

    def test_welcome_callback(self, client: TestClient, meishi_config: MeishiConfig):
        body = _sign_body(meishi_config.secret, {"userOa": "zhangsan", "robotId": "MIS_ROBOT_x"})
        resp = client.post("/api/meishi/callback/welcome", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 1
        assert data["data"]["welcomeText"] == "欢迎"


class TestMeishiSSE:
    def test_sse_frames(self):
        chunk = format_meishi_sse_chunk(message="hello")
        assert chunk.startswith(b"data:")
        assert b"hello" in chunk
        done = format_meishi_sse_done()
        assert done == b"data:[Done]\n\n"
