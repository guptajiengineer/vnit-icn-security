from node import Node
from message import Interest
from collections import defaultdict

class PathEntry:
    def __init__(self, name, path, weight = 4, lifetime = 7):
        self.name = name      # a_k
        self.path = path      # s_k (list of node IDs)
        self.weight = weight
        self.lifetime = lifetime
        self.p = 0.0          # p(a_k, s_k)
        
class ExplorationEntry:
    def __init__(self, name, path, lifetime = 7):
        self.name = name      # a_k
        self.path = path      # s_k (list of node IDs)
        self.lifetime = lifetime

class EdgeNode(Node):
    def __init__(self, node_id, coord):
        super().__init__(node_id,False, coord)#review if erroneous
        self.path_exploration_table = []
        self.path_table = []

    def start_exploration(self, name, content_coord, event_loop, TM=10):
        print(f"[{event_loop.time}] {self.id} Starting exploration...")
        for n in self.neighbors:
            event_loop.schedule(1, n.on_interest, Interest(name, [self]), event_loop, content_coord)

        event_loop.schedule(TM, self.on_exploration_timer_expire, name, event_loop)

    def on_data(self, msg, event_loop):
        print(f"[{event_loop.time}] {self.id} received Data({msg.name}) via path {msg.get_path()}")
        sk = msg.path[1:len(msg.path)//2+1]
        EE = ExplorationEntry(msg.name, sk)
        self.path_exploration_table.append(EE) #(ak, sk)
        print(f"[{event_loop.time}] {self.id} added entry !!! "+ "->".join(str(node.id) for node in sk))

    
    def on_interest(self, interest, event_loop):
        # i hope not called.
        print(f"[{event_loop.time}] {self.id} xxxxxx received Interest({interest.name})")

        # Loop prevention
        if self.id in interest.path:
            return

        interest.path.append(self.id)
        # self.path_table.append(interest.path)

    def on_exploration_timer_expire(self, name, event_loop):
        print(f"[{event_loop.time}] {self.id} TM expired → selecting multipaths\n {name}")
        event_loop.stop_all_loops()
        print(f"{self.id} PET")
        for entry  in self.path_exploration_table:
            print(f"{entry.name} - lifetime, {entry.lifetime} {" -> ".join(str(node.id) for node in entry.path)}")
        # calculate path table.
        self.select_multipaths()

    def select_multipaths(self):
    # todo : compute p(a_k, s_k) here
        # max_weight = max(p.weight for p in self.path_exploration_table) if self.path_exploration_table else 1

        for entry in self.path_exploration_table:
            #entry.p = entry.weight / max_weight
            entry.weight = 10 - len(entry.path) # to do calculate weight

        path_tab, provider_map  = self.filter_entries()
        print(f"Filtered path PET set")
        for entry  in path_tab:
            print(f"{entry.name} : lifetime {entry.lifetime} ; weight {entry.weight} ; {" -> ".join(str(node.id) for node in entry.path)}")
        
        # remove low probability paths
        path_tab = [
            p for p in path_tab if p.weight >= 5 #self.PTh#todo: logic for pathweight threshold
        ]
        # Lines 15–25: remove overlapping paths
        selected = []
        print(f"initial path table")
        for entry  in self.path_table:
            print(f"{entry.name} : lifetime {entry.lifetime} ; weight {entry.weight} ; {" -> ".join(str(node.id) for node in entry.path)}")
        
        for p in sorted(path_tab, key=lambda x: x.weight, reverse=True):
            conflict = False
            for s in selected:
                if self.path_overlap(p, s):
                    conflict = True
                    break
            if not conflict:
                selected.append(p)

        self.path_table = selected
        # Debug output
        # print("Selected Multipaths:")
        # for p in self.path_table:
        #     print(f"  Path: {p.path}, p={p.p:.2f}")

        print(f"Final path table")
        for entry  in self.path_table:
            print(f"{entry.name} : lifetime {entry.lifetime} ; weight {entry.weight} ; {" -> ".join(str(node.id) for node in entry.path)}")
        
    def path_overlap(self, p1, p2):
        return {n.id for n in p1.path} & {n.id for n in p2.path}
    
    def filter_entries(self):
        provider_map = defaultdict(list)

        # Step 1: group by provider node
        for entry in self.path_exploration_table:
            name = entry.name
            weight = entry.weight
            path = entry.path
            provider = path[-1]   # last node
            provider_map[provider].append(entry)

        result = []

        # Step 2: keep only max-weight entries per provider
        for provider, group in provider_map.items():
            max_weight = max(e.weight for e in group)
            print(f"max weight is {max_weight} FOR PROVIDER {provider.id}")
            result.extend(e for e in group if e.weight == max_weight)

        return result, provider_map