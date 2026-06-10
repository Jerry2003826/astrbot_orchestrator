class AstrMessageEvent:
    pass

def filter(*args, **kwargs):
    """Stub decorator for command/regex filters."""
    def decorator(fn):
        return fn
    return decorator

filter.command = lambda *a, **kw: (lambda fn: fn)
filter.regex = lambda *a, **kw: (lambda fn: fn)
