import heapq
import itertools
import threading
from utils import debug_print

class EventLoop:

    def __init__(self):
        self.queue = []
        self.time = 0
        self.counter = itertools.count()
        self.STOP_EVENT = threading.Event()
        self.id = ''

    def schedule(self, delay, callback, *args):
        event_time = self.time + delay
        heapq.heappush(self.queue, (event_time, next(self.counter), callback, args))

    def run(self):
        debug_print("\n--- Simulation started ---\n")
        while self.queue and not self.STOP_EVENT.is_set():
            time, _, callback, args = heapq.heappop(self.queue)
            self.time = time
            callback(*args)
        debug_print("\n--- Simulation finished ---\n")
    
    def stop_all_loops(self):
        self.STOP_EVENT.set()
