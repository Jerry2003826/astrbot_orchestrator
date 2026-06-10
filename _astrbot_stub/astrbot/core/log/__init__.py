import logging

class LogManager:
    @staticmethod
    def GetLogger(name: str) -> logging.Logger:
        return logging.getLogger(name)
