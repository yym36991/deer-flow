"""美事回调请求/响应 Pydantic 模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MeishiCommonParams(BaseModel):
    """回调 body 中的通用鉴权与用户字段。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    sign_str: str = Field(default="", alias="signStr")
    random: str = ""
    timestamp: str = ""
    user_oa: str = Field(default="", alias="userOa")
    client_type: str = Field(default="", alias="clientType")
    plat_form: str = Field(default="", alias="platForm")
    token: str = ""
    question_source: str = Field(default="", alias="questionSource")


class PreQARequest(MeishiCommonParams):
    msg_id: str = Field(default="", alias="msgId")
    msg: str = ""
    sender_id: str = Field(default="", alias="senderId")
    sender_source: int | None = Field(default=None, alias="senderSource")
    to_id: str = Field(default="", alias="toId")
    to_source: int | None = Field(default=None, alias="toSource")
    robot_id: str = Field(default="", alias="robotId")
    content: str = ""
    quote: str = ""
    type: str = ""


class PreQAResponseData(BaseModel):
    answer: str = ""
    answer_msg_type: str = Field(default="", alias="answerMsgType")
    answer_msg_content: str = Field(default="", alias="answerMsgContent")
    modify_msg: str = Field(default="", alias="modifyMsg")
    scalar_map: dict[str, list[str]] = Field(default_factory=dict, alias="scalarMap")
    reply_type: int = Field(default=0, alias="replyType")
    reply_answer: str = Field(default="", alias="replyAnswer")


class InQARequest(MeishiCommonParams):
    msg_id: str = Field(default="", alias="msgId")
    msg: str = ""
    sender_id: str = Field(default="", alias="senderId")
    to_id: str = Field(default="", alias="toId")
    conversation_id: str = Field(default="", alias="conversationId")


class InQAResponseData(BaseModel):
    answer: str = ""
    answer_msg_type: str = Field(default="", alias="answerMsgType")
    answer_msg_content: str = Field(default="", alias="answerMsgContent")
    jump_action: dict[str, Any] | None = Field(default=None, alias="jumpAction")


class ButtonRequest(MeishiCommonParams):
    app_id: str = Field(default="", alias="appId")
    topic_id: str = Field(default="", alias="topicId")
    data: dict[str, Any] = Field(default_factory=dict)
    msg_id: str = Field(default="", alias="msgId")
    sender_id: str = Field(default="", alias="senderId")
    to_id: str = Field(default="", alias="toId")
    session_id: str = Field(default="", alias="sessionId")


class ButtonResponseData(BaseModel):
    answer: str = ""
    answer_msg_type: str = Field(default="", alias="answerMsgType")
    answer_msg_content: str = Field(default="", alias="answerMsgContent")


class WelcomeRequest(MeishiCommonParams):
    robot_id: str = Field(default="", alias="robotId")
    robot_name: str = Field(default="", alias="robotName")
    page_type: int = Field(default=0, alias="pageType")
    extra: str = ""
    user_id: str = Field(default="", alias="userId")


class WelcomeCmdItem(BaseModel):
    text: str
    cmd: str
    action_type: str = Field(default="backInputbox", alias="actionType")
    open_url: str | None = Field(default=None, alias="openUrl")


class WelcomeResponseData(BaseModel):
    welcome_text: str = Field(default="", alias="welcomeText")
    answer_msg_type: str = Field(default="", alias="answerMsgType")
    answer_msg_content: str = Field(default="", alias="answerMsgContent")
    session_extend: str = Field(default="", alias="sessionExtend")
    cmd_list: list[WelcomeCmdItem] = Field(default_factory=list, alias="cmdList")


class MessageSyncRequest(MeishiCommonParams):
    msg_id: str = Field(default="", alias="msgId")
    robot_id: str = Field(default="", alias="robotId")
    type: str = ""
    msg: str = ""
    content: str = ""
    sender_id: str = Field(default="", alias="senderId")
    sender_source: int | None = Field(default=None, alias="senderSource")
    to_id: str = Field(default="", alias="toId")
    to_source: int | None = Field(default=None, alias="toSource")


class MeishiApiResponse(BaseModel):
    code: int = 1
    msg: str = ""
    data: Any = None
