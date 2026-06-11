"""astrbot.core.computer.computer_client 测试桩，对齐 v4.25.5 get_booter 签名。

真实实现读取 provider_settings.computer_use_runtime（none/local/sandbox）
与 provider_settings.sandbox.booter 决定返回的 ComputerBooter。
"""

from typing import Any


class ComputerBooter:
    pass


async def get_booter(context: Any, session_id: str) -> ComputerBooter:
    config = context.get_config(umo=session_id)
    runtime = config.get("provider_settings", {}).get("computer_use_runtime", "local")
    if runtime == "none":
        raise RuntimeError("Sandbox runtime is disabled by configuration.")
    raise NotImplementedError("stub: 测试请注入 Fake booter")
