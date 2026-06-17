DEBUG = False
LMM = "LMM-1"
CACHEHIT = 0

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)