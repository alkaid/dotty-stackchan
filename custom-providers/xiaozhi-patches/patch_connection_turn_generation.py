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
        '''    def chat(self, query, depth=0):
        # 保存当前任务的sentence_id到局部变量，避免被新任务覆盖
        current_sentence_id = None
''',
        '''    def chat(self, query, depth=0, turn_generation=None):
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
                None, depth=depth + 1, turn_generation=turn_generation
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
