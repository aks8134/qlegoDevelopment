import time
from contextlib import contextmanager

@contextmanager
def timer(label="block"):
    result = {}  # will be filled on exit
    wall0 = time.perf_counter()
    cpu0  = time.process_time()
    try:
        yield result
    finally:
        wall1 = time.perf_counter()
        cpu1  = time.process_time()
        result["label"] = label
        result["wall"] = wall1 - wall0
        result["cpu"]  = cpu1 - cpu0
        result["non_cpu"] = result["wall"] - result["cpu"]
