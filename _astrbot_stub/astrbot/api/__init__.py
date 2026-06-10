from .star import Context, Star

class AstrBotConfig(dict):
    pass

logger = __import__("logging").getLogger("astrbot.api")

__all__ = ["AstrBotConfig", "Context", "Star", "logger"]
