"""美事流式输出状态：累积助手正文。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MeishiStreamState:
    answer_text: str = ""

    def set_answer(self, text: str) -> None:
        self.answer_text = text or ""

    def display_snapshot(self) -> str:
        return self.answer_text.strip()
