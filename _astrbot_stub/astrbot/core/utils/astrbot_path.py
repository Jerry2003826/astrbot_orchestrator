import os
import tempfile


def get_astrbot_data_path() -> str:
    return os.path.join(tempfile.gettempdir(), "astrbot_test_data")


def get_astrbot_skills_path() -> str:
    return os.path.join(tempfile.gettempdir(), "astrbot_test_skills")
