"""
Skill 创建/管理工具

功能：
- 动态创建 SKILL.md 文件
- 编辑现有 Skill
- 管理 Skill 生命周期
"""

import os
from pathlib import Path
from typing import Any, cast

from astrbot.api import logger

from ..shared import ensure_within_base, slugify_identifier


class SkillCreatorTool:
    """
    Skill 创建/管理工具

    通过 AstrBot 的 SkillManager 管理 Skills
    """

    def __init__(self, context: Any) -> None:
        self.context = context
        self._skill_manager: Any | None = None

    @staticmethod
    def _extract_markdown_block(content: str) -> str:
        """从 LLM 响应中安全提取 Markdown 正文。

        基于 ``str.find``/``str.rfind`` 切片实现（不依赖正则，规避超长
        文本的回溯性能问题）：取第一个围栏到最后一个围栏之间的内容，
        因此正文内部嵌套的代码块不会被截断；围栏不规范（单行、缺收尾）
        或没有代码块时逐级回退，绝不抛 IndexError。
        """

        stripped = content.strip()

        open_pos = stripped.find("```")
        if open_pos == -1:
            return stripped

        after_open = open_pos + 3
        newline_pos = stripped.find("\n", after_open)
        next_fence_pos = stripped.find("```", after_open)

        if newline_pos != -1 and (next_fence_pos == -1 or newline_pos < next_fence_pos):
            # 常规多行围栏：跳过语言标记行（```markdown 等）
            body_start = newline_pos + 1
        else:
            # 单行围栏（```# 内容```）或紧跟收尾围栏
            body_start = after_open

        # close_pos == body_start 意味着 rfind 命中的是紧邻的收尾围栏（空代码块），
        # 此时应返回空串而非把围栏当正文；命中开头围栏自身时 close_pos < body_start。
        close_pos = stripped.rfind("```")
        if close_pos >= body_start:
            return stripped[body_start:close_pos].strip()

        # 缺收尾围栏：保留围栏后的全部内容
        return stripped[body_start:].strip()

    def _get_skill_manager(self) -> Any | None:
        """获取 AstrBot 的 SkillManager。

        优先复用宿主托管实例，避免与系统运行时状态隔离；
        宿主未暴露时才退回自行构造。
        """
        if self._skill_manager is None:
            host_manager = getattr(self.context, "skill_manager", None)
            if host_manager is not None:
                self._skill_manager = host_manager
                return self._skill_manager
            try:
                from astrbot.core.skills.skill_manager import SkillManager

                self._skill_manager = SkillManager()
            except ImportError:
                logger.warning("无法导入 SkillManager")
        return self._skill_manager

    def _get_skills_path(self) -> str:
        """获取 Skills 存储路径"""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_skills_path

            return cast(str, get_astrbot_skills_path())
        except ImportError:
            # 备用路径
            return os.path.expanduser("~/.astrbot/data/skills")

    def list_skills(self) -> str:
        """列出所有 Skills"""
        sm = self._get_skill_manager()
        if not sm:
            return "❌ Skill 管理器不可用"

        try:
            skills = sm.list_skills(active_only=False)

            if not skills:
                return "📚 暂无 Skill\n\n💡 使用 `/skill create <名称>` 创建新 Skill"

            lines = ["📚 已安装的 Skills：\n"]

            for skill in skills:
                status = "✅" if skill.active else "❌"
                lines.append(f"{status} **{skill.name}**")
                if skill.description:
                    lines.append(f"   {skill.description[:50]}...")
                lines.append(f"   📁 {skill.path}")

            return "\n".join(lines)

        except Exception as e:
            return f"❌ 获取 Skill 列表失败: {str(e)}"

    def read_skill(self, name: str) -> str:
        """读取 Skill 内容"""
        sm = self._get_skill_manager()
        if not sm:
            return "❌ Skill 管理器不可用"

        try:
            safe_name = slugify_identifier(name, default="generated_skill")
            skills_path = self._get_skills_path()
            skill_dir = Path(skills_path) / safe_name

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                skill_md = skill_dir / "skill.md"

            if not skill_md.exists():
                return f"❌ Skill `{safe_name}` 不存在"

            content = skill_md.read_text(encoding="utf-8")
            return f"📄 Skill: **{safe_name}**\n\n```markdown\n{content}\n```"

        except Exception as e:
            return f"❌ 读取 Skill 失败: {str(e)}"

    async def create_skill(
        self,
        name: str,
        description: str,
        content: str,
        scripts: dict[str, str] | None = None,
    ) -> str:
        """
        创建新 Skill

        Args:
            name: Skill 名称（目录名）
            description: 简短描述
            content: SKILL.md 内容
            scripts: 可选的脚本文件 {filename: content}

        Returns:
            创建结果
        """
        try:
            safe_name = slugify_identifier(name, default="generated_skill")
            skills_path = self._get_skills_path()
            skill_dir = Path(skills_path) / safe_name

            # 检查是否已存在
            if skill_dir.exists():
                return f"❌ Skill `{safe_name}` 已存在，请使用其他名称或先删除"

            # 创建目录（防范中间层级被同名普通文件占用的情况）
            base_dir = Path(skills_path)
            if base_dir.exists() and not base_dir.is_dir():
                return f"❌ Skills 根路径被同名文件占用: `{skills_path}`"
            try:
                skill_dir.mkdir(parents=True, exist_ok=True)
            except (NotADirectoryError, FileExistsError) as e:
                return f"❌ 无法创建 Skill 目录（路径被普通文件占用）: {e}"

            # 创建 SKILL.md
            skill_md = skill_dir / "SKILL.md"

            # 添加 frontmatter
            full_content = f"""---
description: {description}
---

{content}
"""
            skill_md.write_text(full_content, encoding="utf-8")

            # 创建脚本文件（如果有）
            if scripts:
                scripts_dir = skill_dir / "scripts"
                scripts_dir.mkdir(exist_ok=True)

                for filename, script_content in scripts.items():
                    script_path = ensure_within_base(scripts_dir, filename)
                    script_path.write_text(script_content, encoding="utf-8")

            # 激活 Skill
            sm = self._get_skill_manager()
            if sm:
                sm.set_skill_active(safe_name, True)

            return (
                f"✅ Skill `{safe_name}` 创建成功！\n\n📁 路径: {skill_dir}\n\n💡 Skill 已自动激活"
            )

        except Exception as e:
            logger.error(f"创建 Skill 失败: {e}")
            return f"❌ 创建失败: {str(e)}"

    async def edit_skill(self, name: str, new_content: str) -> str:
        """编辑 Skill 内容"""
        try:
            safe_name = slugify_identifier(name, default="generated_skill")
            skills_path = self._get_skills_path()
            skill_dir = Path(skills_path) / safe_name

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                skill_md = skill_dir / "skill.md"

            if not skill_md.exists():
                return f"❌ Skill `{safe_name}` 不存在"

            # 备份原文件
            backup_path = skill_md.with_suffix(".md.bak")
            backup_path.write_text(skill_md.read_text(encoding="utf-8"), encoding="utf-8")

            # 写入新内容
            skill_md.write_text(new_content, encoding="utf-8")

            return f"✅ Skill `{safe_name}` 已更新\n\n💡 原文件已备份为 {backup_path.name}"

        except Exception as e:
            return f"❌ 编辑失败: {str(e)}"

    def delete_skill(self, name: str) -> str:
        """删除 Skill"""
        sm = self._get_skill_manager()
        if not sm:
            return "❌ Skill 管理器不可用"

        try:
            safe_name = slugify_identifier(name, default="generated_skill")
            sm.delete_skill(safe_name)
            return f"✅ Skill `{safe_name}` 已删除"
        except Exception as e:
            return f"❌ 删除失败: {str(e)}"

    async def generate_skill_from_description(
        self,
        name: str,
        user_description: str,
        provider_id: str,
    ) -> str:
        """
        根据用户描述自动生成 Skill

        使用 LLM 生成 SKILL.md 内容；失败时与类内其他方法保持一致，
        返回 ``❌`` 前缀的错误信息而非抛出异常。
        """
        prompt = f"""请根据以下描述生成一个 AstrBot Skill 的 SKILL.md 文件内容。

用户描述：{user_description}

Skill 名称：{name}

SKILL.md 文件格式示例：
```markdown
---
description: 简短的功能描述
---

# {name}

## 功能描述
详细描述这个 Skill 的功能...

## 使用方法
如何使用这个 Skill...

## 示例
一些使用示例...

## 依赖
如果需要依赖的工具或 API...
```

请生成完整的 SKILL.md 内容，只输出 Markdown 内容，不要其他解释。"""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是一个专业的 AstrBot Skill 开发者。",
            )

            content = cast(str, response.completion_text)
            return self._extract_markdown_block(content)

        except Exception as e:
            logger.error(f"生成 Skill 内容失败: {e}")
            return f"❌ 生成 Skill 内容失败: {str(e)}"
