"""Apply Dotty's turn-scoped abort patch to the pinned xiaozhi server.

The upstream connection uses one ``client_abort`` boolean for every executor
thread. A barge-in leaves it true, so the next turn drops its first LLM chunk;
clearing it at submission time can instead revive the old thread. The Dotty
voice entry point passes a monotonically increasing generation into ``chat``.
These checked source edits make stale threads exit permanently and clear the
shared flag only after the new turn owns a fresh sentence id.
"""

from __future__ import annotations

import pathlib
import sys


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"xiaozhi connection patch anchor {label!r} matched {count} times"
        )
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    source = _replace_once(
        source,
        '''        self.timeout_seconds = (
                int(self.config.get("close_connection_no_voice_time", 120)) + 60
        )  # 在原来第一道关闭的基础上加60秒，进行二道关闭
        self.timeout_task = None
''',
        '''        self.timeout_seconds = (
                int(self.config.get("close_connection_no_voice_time", 120)) + 60
        )  # 在原来第一道关闭的基础上加60秒，进行二道关闭
        # Dotty keeps an idle device channel open for dashboard commands.
        # WebSocket ping/pong already detects dead peers; voice inactivity is
        # not evidence that the physical robot is offline.
        self.keep_device_connection_alive = self.config.get(
            "keep_device_connection_alive", True
        )
        self.timeout_task = None
''',
        "persistent device connection flag",
    )
    source = _replace_once(
        source,
        '''    async def _check_timeout(self):
        """检查连接超时"""
        try:
''',
        '''    async def _check_timeout(self):
        """检查连接超时"""
        if self.keep_device_connection_alive:
            self.logger.bind(tag=TAG).info(
                "Dotty persistent device connection enabled; idle timeout disabled"
            )
            return
        try:
''',
        "persistent device connection timeout gate",
    )
    source = _replace_once(
        source,
        '''    def chat(self, query, depth=0):
        # 保存当前任务的sentence_id到局部变量，避免被新任务覆盖
        current_sentence_id = None
''',
        '''    def chat(self, query, depth=0, turn_generation=None, turn_id=None):
        # DOTTY-PATCH: a superseded executor thread must never emit into a
        # replacement turn, even after the replacement clears client_abort.
        if (
                turn_generation is not None
                and turn_generation != getattr(self, "_dotty_chat_generation", None)
        ):
            self.logger.bind(tag=TAG).debug(
                f"Skipping stale chat turn generation={turn_generation}"
            )
            return False

        # 保存当前任务的sentence_id到局部变量，避免被新任务覆盖
        current_sentence_id = None
''',
        "chat signature",
    )
    source = _replace_once(
        source,
        '''            else:
                llm_responses = self.llm.response(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(
                        memory_str, self.config.get("voiceprint", {})
                    ),
                )
''',
        '''            else:
                llm_kwargs = {}
                if (
                        turn_id is not None
                        and self.config.get("selected_module", {}).get("LLM")
                        == "PiVoiceLLM"
                ):
                    llm_kwargs["turn_id"] = turn_id
                llm_responses = self.llm.response(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(
                        memory_str, self.config.get("voiceprint", {})
                    ),
                    **llm_kwargs,
                )
''',
        "PiVoiceLLM turn id",
    )
    source = _replace_once(
        source,
        '''            self.sentence_id = current_sentence_id  # 更新共享属性
            self.dialogue.put(Message(role="user", content=query))
''',
        '''            self.sentence_id = current_sentence_id  # 更新共享属性
            # Switch sentence ownership before clearing abort. Stale TTS audio
            # is filtered by sentence_id, while stale LLM threads are filtered
            # by turn_generation below.
            if turn_generation is not None:
                self.client_abort = False
                self.logger.bind(tag=TAG).debug(
                    f"Activated chat turn generation={turn_generation} "
                    f"sentence_id={current_sentence_id}"
                )
            self.dialogue.put(Message(role="user", content=query))
''',
        "new sentence ownership",
    )
    source = _replace_once(
        source,
        '''            for response in llm_responses:
                if self.client_abort:
                    break
''',
        '''            for response in llm_responses:
                if self.client_abort or (
                        turn_generation is not None
                        and turn_generation
                        != getattr(self, "_dotty_chat_generation", None)
                ):
                    break
''',
        "stream abort check",
    )
    source = _replace_once(
        source,
        '''            return
        # 处理function call
''',
        '''            return

        if (
                turn_generation is not None
                and turn_generation != getattr(self, "_dotty_chat_generation", None)
        ):
            self.logger.bind(tag=TAG).debug(
                f"Discarding stale chat turn generation={turn_generation}"
            )
            return False

        # 处理function call
''',
        "post-stream stale check",
    )
    source = _replace_once(
        source,
        '''        # 存储对话内容
        if len(response_message) > 0:
''',
        '''        if (
                turn_generation is not None
                and turn_generation != getattr(self, "_dotty_chat_generation", None)
        ):
            return False

        # 存储对话内容
        if len(response_message) > 0:
''',
        "post-tool stale check",
    )
    source = _replace_once(
        source,
        '''            self.chat(None, depth=depth + 1)
''',
        '''            self.chat(
                None, depth=depth + 1, turn_generation=turn_generation,
                turn_id=turn_id,
            )
''',
        "recursive chat generation",
    )
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} /path/to/core/connection.py")
    path = pathlib.Path(sys.argv[1])
    path.write_text(patch_source(path.read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main()
