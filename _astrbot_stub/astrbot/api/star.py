class Context:
    pass

class Star:
    pass

def register(*, name, desc="", version="", author=""):
    def decorator(cls):
        return cls
    return decorator
