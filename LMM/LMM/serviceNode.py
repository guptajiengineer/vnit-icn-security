import math
from message import Data, Interest
from node import Node
class ServiceNode(Node):
    def __init__(self, node_id, has_content, coord, weight=1):
        super().__init__(node_id, has_content, coord)
        self.weight = weight
        self.cache = set()

    def on_interest(self, msg, event_loop, content_coord):
        print(f"[{event_loop.time}] {self.id} received Interest({msg.name}) via path {msg.get_path()}")
        prev_node = msg.path[-1]#last node of path set sk
        # lengt = len(msg.path) - 1
        # prev_node = msg.path[lengt]
        if self.coord.distance_to(content_coord) >= prev_node.coord.distance_to(content_coord):
            return

        msg.path.append(self)

        # if msg.name in self.cache:
        if self.has_content:#send data with ak, sk along sk path
            # data = Data(msg.name, msg.path.copy())# todo: retrieve from cache
            event_loop.schedule(1, prev_node.on_data, Data(msg.name, msg.path.copy()), event_loop)
            return

        if self.weight > 0:
            for n in self.neighbors:
                if n not in msg.path:#check once if needed
                   event_loop.schedule(1, n.on_interest, Interest(msg.name, msg.path.copy()), event_loop, content_coord)

    def on_data(self, data, event_loop):
        print(f"[{event_loop.time}] {self.id} received Data({data.name}) via path {data.get_path()}")
        # get nodeiId of the the prev node in datapath
        # get node & call on_data.
        # self.paths.append(data.path_set)
        idx = data.path.index(self)
        data.path.append(self)
        event_loop.schedule(1, data.path[idx - 1].on_data, Data(data.name, data.path.copy()), event_loop)


# # -------------------------
# # Service Node (SN)
# # -------------------------
# class ServiceNode(Node):
#     def __init__(self, node_id, cache=False):
#         super().__init__(node_id)
#         self.cache = cache

#     def on_interest(self, interest, loop, source):
#         print(f"[{loop.time}] SN {self.id} received Interest({interest.content})")

#         if self.id in interest.path_set:
#             return  # loop prevention

#         interest.path_set.add(self.id)

#         if self.cache:
#             print(f"[{loop.time}] SN {self.id} CACHE HIT → sending Data")
#             data = Data(interest.content, interest.path_set.copy())
#             loop.schedule(1, source.on_data, data, loop)
#             return

#         # Forward Interest (multipath)
#         for n in self.neighbors:
#             loop.schedule(1, n.on_interest, interest, loop, self)


# # -------------------------
# # Edge Node (EN)
# # -------------------------
# class EdgeNode(Node):
#     def __init__(self, node_id):
#         super().__init__(node_id)
#         self.paths = []

#     def start_exploration(self, content, loop):
#         print(f"[{loop.time}] EN {self.id} starts exploration for '{content}'")
#         interest = Interest(content, path_set={self.id})
#         for n in self.neighbors:
#             loop.schedule(1, n.on_interest, interest, loop, self)

#     def on_data(self, data, loop):
#         print(f"[{loop.time}] EN {self.id} received Data({data.content}) via path {data.path_set}")
#         self.paths.append(data.path_set)