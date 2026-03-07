"""
自我诊断和 Debug 工具

功能：
- 分析错误日志
- 诊断系统状态
- 提供修复建议
"""

from collections import deque
from datetime import datetime
import logging
import sys
import traceback
from typing import Any, ClassVar, cast

logger = logging.getLogger(__name__)


class SelfDebugger:
    """
    自我诊断和 Debug 工具

    能够分析错误、诊断问题、提供修复建议
    """

    # 最近的错误记录
    _error_history: ClassVar[deque[dict[str, Any]]] = deque(maxlen=50)

    def __init__(self, context: Any) -> None:
        self.context = context

    @classmethod
    def record_error(cls, error: Exception, context: dict[str, Any] | None = None) -> None:
        """记录错误"""
        cls._error_history.append(
            {
                "time": datetime.now().isoformat(),
                "error_type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
                "context": context or {},
            }
        )

    def get_recent_errors(self, limit: int = 10) -> str:
        """获取最近的错误"""
        if not self._error_history:
            return "📋 暂无错误记录"

        errors = list(self._error_history)[-limit:]

        lines = [f"📋 最近 {len(errors)} 条错误：\n"]

        for i, err in enumerate(reversed(errors), 1):
            time = err["time"][:19]
            error_type = err["error_type"]
            message = err["message"][:100]

            lines.append(f"**{i}. [{time}] {error_type}**")
            lines.append(f"   {message}...")
            lines.append("")

        return "\n".join(lines)

    async def analyze_error(
        self,
        error: Exception,
        traceback_info: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        分析错误并提供修复建议

        Args:
            error: 异常对象
            traceback_info: 完整的 traceback
            context: 上下文信息

        Returns:
            分析结果和建议
        """
        # 记录错误
        self.record_error(error, context)

        error_type = type(error).__name__
        error_message = str(error)

        # 基础分析
        analysis: list[str] = []

        # 常见错误快速诊断
        if "ConnectionError" in error_type or "Timeout" in str(error):
            analysis.append("🔍 **网络连接问题**")
            analysis.append("- 检查网络连接是否正常")
            analysis.append("- 检查目标服务是否可用")
            analysis.append("- 考虑增加超时时间")

        elif "Permission" in error_type or "权限" in error_message:
            analysis.append("🔍 **权限问题**")
            analysis.append("- 检查是否有管理员权限")
            analysis.append("- 检查文件/目录权限")

        elif "ModuleNotFoundError" in error_type or "ImportError" in error_type:
            module = error_message.split("'")[1] if "'" in error_message else "unknown"
            analysis.append(f"🔍 **缺少依赖: {module}**")
            analysis.append(f"- 尝试安装: `pip install {module}`")

        elif "JSONDecodeError" in error_type:
            analysis.append("🔍 **JSON 解析错误**")
            analysis.append("- 返回的数据不是有效的 JSON")
            analysis.append("- 检查 API 响应格式")

        elif "AttributeError" in error_type:
            analysis.append("🔍 **属性访问错误**")
            analysis.append("- 对象可能为 None")
            analysis.append("- 检查对象类型是否正确")

        elif "KeyError" in error_type:
            analysis.append("🔍 **键不存在**")
            analysis.append("- 字典中缺少指定的键")
            analysis.append("- 使用 .get() 方法避免错误")

        else:
            analysis.append(f"🔍 **{error_type}**")
            analysis.append(f"- 错误信息: {error_message}")

        # 提取关键堆栈信息
        if traceback_info:
            tb_lines = traceback_info.strip().split("\n")
            relevant_lines = [
                line for line in tb_lines if "astrbot" in line.lower() or "File" in line
            ][-4:]
            if relevant_lines:
                analysis.append("\n📍 **错误位置:**")
                for line in relevant_lines:
                    analysis.append(f"```\n{line.strip()}\n```")

        return "\n".join(analysis)

    async def get_system_status(self) -> str:
        """获取系统状态"""
        lines: list[str] = ["🖥️ **系统状态**\n"]

        # Python 版本
        lines.append(f"• Python: {sys.version.split()[0]}")

        # 内存使用
        try:
            import psutil

            memory = psutil.virtual_memory()
            lines.append(f"• 内存: {memory.percent}% 使用")
        except ImportError:
            lines.append("• 内存: 无法获取 (需要 psutil)")

        # AstrBot 状态
        try:
            # 检查插件数量
            stars = self.context.get_all_stars()
            active_stars = [s for s in stars if s.activated]
            lines.append(f"• 插件: {len(active_stars)} 个激活")

            # 检查模型提供商
            providers = self.context.provider_manager.get_all_providers()
            lines.append(f"• 模型提供商: {len(providers)} 个")

            # 检查 MCP 服务
            mcp_clients = getattr(self.context.provider_manager.llm_tools, "mcp_client_dict", {})
            active_mcp = [c for c in mcp_clients.values() if c.active]
            lines.append(f"• MCP 服务: {len(active_mcp)} 个连接")

        except Exception as e:
            lines.append(f"• AstrBot 状态: 部分获取失败 ({e})")

        # 最近错误数
        lines.append(f"• 最近错误: {len(self._error_history)} 条")

        return "\n".join(lines)

    async def analyze_problem(
        self,
        problem_description: str,
        provider_id: str,
    ) -> str:
        """
        分析用户描述的问题

        使用 LLM 分析问题并提供解决方案
        """
        # 收集上下文
        system_status = await self.get_system_status()
        recent_errors = self.get_recent_errors(5)

        prompt = f"""用户遇到了以下问题：

{problem_description}

## 系统状态
{system_status}

## 最近错误
{recent_errors}

请分析可能的原因，并提供解决方案：

1. 问题诊断：分析可能的原因
2. 解决步骤：具体的解决方法
3. 预防建议：如何避免类似问题"""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是一个 AstrBot 技术支持专家，擅长诊断和解决问题。",
            )

            return cast(str, response.completion_text)

        except Exception as e:
            return f"❌ 分析失败: {str(e)}"

    async def suggest_fix(
        self,
        error: Exception,
        code_context: str,
        provider_id: str,
    ) -> str:
        """
        为代码错误建议修复
        """
        prompt = f"""以下代码产生了错误，请提供修复建议：

## 错误信息
类型: {type(error).__name__}
消息: {str(error)}

## 代码上下文
```python
{code_context}
```

## Traceback
```
{traceback.format_exc()}
```

请分析错误原因，并提供修复后的代码。"""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是一个 Python 调试专家。",
            )

            return cast(str, response.completion_text)

        except Exception as e:
            return f"❌ 无法生成修复建议: {str(e)}"
