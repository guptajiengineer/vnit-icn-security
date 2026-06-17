from message import Interest
# =============================
# User
# =============================
class User:
    def __init__(self, user_id, edge_node):
        self.id = user_id
        self.edge = edge_node

    def request(self, content, loop):
        print(f"[{loop.time}] User {self.id} requests {content}")
        interest = Interest(content, path=[self.edge.id])
        for n in self.edge.neighbors:
            loop.schedule(1, n.on_interest, interest, loop, self.edge)

