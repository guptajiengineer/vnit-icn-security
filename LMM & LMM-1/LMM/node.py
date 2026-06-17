from message import Data

class Node:
    def __init__(self, node_id, has_content=False, coord =[], is_edge=False, cache=False):
        self.id = node_id
        self.coord = coord
        self.is_edge = is_edge
        self.has_content = has_content
        self.cache = cache
        self.neighbors = []

    def connect(self, other):
        if other not in self.neighbors:
            self.neighbors.append(other)
            other.neighbors.append(self)
        # self.neighbors.extend(nodes)

    def on_interest(self, msg, event_loop):
        pass

    def on_data(self, msg, event_loop):
        pass