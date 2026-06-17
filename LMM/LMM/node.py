# class Node:
#     def __init__(self, node_id, coord):
#         self.id = node_id
#         self.coord = coord
#         self.neighbors = []

#     def on_interest(self, msg, event_loop):
#         pass

#     def on_data(self, msg, event_loop):
#         pass


# =============================
# Node (EN & SN)
# =============================
from message import Data
class Node:
    def __init__(self, node_id, has_content=False, coord =[], is_edge=False, cache=False):
        self.id = node_id
        self.coord = coord
        self.is_edge = is_edge
        self.has_content = has_content
        self.cache = cache
        self.neighbors = []

    def connect(self, *nodes):
        self.neighbors.extend(nodes)

    def on_interest(self, msg, event_loop):
        pass

    def on_data(self, msg, event_loop):
        pass
    # -------------------------
    # Interest handler
    # -------------------------
    # def on_interest(self, interest, loop, incoming):
    #     print(f"[{loop.time}] {self.id} received Interest({interest.name})")

    #     # Loop prevention
    #     if self.id in interest.path:
    #         return

    #     interest.path.append(self.id)

    #     # If content exists here
    #     if self.has_content or self.cache:
    #         print(f"[{loop.time}] {self.id} satisfies Interest → Data")
    #         data = Data(interest.name, interest.path.copy())
    #         loop.schedule(1, incoming.on_data, data, loop, self)
    #         return

    #     # Forward Interest (multipath)
    #     for n in self.neighbors:
    #         if n != incoming:
    #             loop.schedule(1, n.on_interest, interest, loop, self)

    # # -------------------------
    # # Data handler
    # # -------------------------
    # def on_data(self, data, loop, incoming):
    #     print(f"[{loop.time}] {self.id} received Data({data.name}) via {data.path}")

    #     # Cache data if allowed
    #     if self.cache:
    #         self.has_content = True

    #     # If Edge Node → store path
    #     if self.is_edge:
    #         self.path_table.append(data.path)
    #         return

    #     # Forward Data backward along path
    #     if len(data.path) > 1:
    #         data.path.pop()  # remove current
    #         prev_id = data.path[-1]
    #         for n in self.neighbors:
    #             if n.id == prev_id:
    #                 loop.schedule(1, n.on_data, data, loop, self)
    #                 break

