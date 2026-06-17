from message import Interest
from utils import debug_print
# User
REQUEST_DELAY = 2

class User:
    def __init__(self, uid, edge_nodes, metrics, TM = 10):
        self.uid = uid
        self.edge_nodes = edge_nodes
        self.TM = TM
        self.has_timer_expired = False
        self.isRetry = False
        self.dataReceived = False
        self.isEnabled = False
        self.metrics = metrics
        self.pending_requests = {} 

    def request(self, name, event_loop):  
        if not self.isRetry:  
            event_loop.schedule(self.TM, self.on_timer_expire, name, event_loop)
            self.isRetry = True
        if not self.has_timer_expired:
            debug_print(f"[{event_loop.time}] User {self.uid} retrieves {name}")
            # event_loop.schedule(0, self.edge.on_user_interest, name, event_loop)
            for n in self.edge_nodes:
                if n.state != "READY":
                    event_loop.schedule(1.0, self.request, name, event_loop)
                    return
                event_loop.schedule(1, n.on_user_interest, name, event_loop, None, self) #new event loop right?shud be independent
                self.pending_requests[name] = event_loop.time
    
    def on_data(self, msg, event_loop, hops):
        if not self.has_timer_expired:
            self.dataReceived = True
            debug_print(f"[{event_loop.time}] User {self.uid} received Data({msg.name}) via path {msg.get_path()}. THANKSSSSSSSSSSSSSSSSSSSSSS!!")
            start_time = self.pending_requests.pop(msg.name, None)
            if start_time is None:
                return

            duration = event_loop.time - start_time
            # hops = len(msg.path) - 1   # nodes traversed

            self.metrics.record(
                user_id=self.uid,
                run_id=9,
                hops=hops,
                duration=duration
            )

    def on_timer_expire(self, name, event_loop):
        if not self.dataReceived :
            debug_print(f"[{event_loop.time}] {self.uid} TM expired → USER ANGRY!!!!!!!!!!!!!!!\n {name}")
        self.has_timer_expired = True
        # event_loop.stop_all_loops()

    def enable_requests(self, event_loop):
        self.isEnabled = True
        debug_print(f"[{event_loop.time}] User {self.uid} enabled")
        # event_loop.schedule(REQUEST_DELAY, self.request)