
from utils import debug_print
class SimulationController:
    def __init__(self, sim, edges, users):
        self.sim = sim
        self.edges = edges
        self.users = users
        self.ready_edges = set()

    def edge_ready(self, edge_id, event_loop):
        self.ready_edges.add(edge_id)

        if len(self.ready_edges) == len(self.edges):
            debug_print(f"[{event_loop.time}] All edges READY")
            self.activate_users(event_loop)

    def activate_users(self, event_loop):
        for user in self.users:
            event_loop.schedule(0.0, user.enable_requests, event_loop)
