"""astrbot.core.utils.astrbot_path 测试桩，对齐 v4.25.5 函数名。

根目录默认落在临时目录，可用环境变量 ASTRBOT_STUB_ROOT 覆盖，
便于测试隔离文件系统副作用。
"""

import os
import tempfile


def get_astrbot_root() -> str:
    root = os.environ.get("ASTRBOT_STUB_ROOT")
    if root:
        return os.path.realpath(root)
    return os.path.realpath(os.path.join(tempfile.gettempdir(), "astrbot_stub_root"))


def get_astrbot_data_path() -> str:
    return os.path.realpath(os.path.join(get_astrbot_root(), "data"))


def get_astrbot_config_path() -> str:
    return os.path.realpath(os.path.join(get_astrbot_data_path(), "config"))


def get_astrbot_plugin_path() -> str:
    return os.path.realpath(os.path.join(get_astrbot_data_path(), "plugins"))


def get_astrbot_plugin_data_path() -> str:
    return os.path.realpath(os.path.join(get_astrbot_data_path(), "plugin_data"))


def get_astrbot_skills_path() -> str:
    return os.path.realpath(os.path.join(get_astrbot_data_path(), "skills"))


def get_astrbot_temp_path() -> str:
    return os.path.realpath(os.path.join(get_astrbot_data_path(), "temp"))
