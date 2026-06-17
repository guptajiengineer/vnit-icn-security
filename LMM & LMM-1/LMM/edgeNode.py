from node import *
from message import Interest
from collections import defaultdict
from pathUtils import PathEntry
import utils # import debug_print, LMM
from utils import debug_print
from content import *
import math
from cachingUtility import caching_decision

class PendingInterestTable:
    def __init__(self, timeout=5):
        self.chunk_table = {}  
        # (name, byte_range) -> {
        #     "users": set(),
        #     "status": "pending" | "buffered"
        #     "hop_count":
        # }
        self.user_table = {}    # (user, name) -> tracking info
        self.timeout = timeout

    def add_interest(self, content_name, byte_range, user):
        key = (content_name, byte_range)
        if key in self.chunk_table:
            self.chunk_table[key].add(user)
            return True  # already pending, just aggregated
        else:
            self.chunk_table[key] = {user}
            return False  # first interest for this chunk
            
    def add_interest(self, content_name, byte_range, user):
        key = (content_name, byte_range)

        entry = self.chunk_table.get(key)

        # Case 1: chunk exists and already buffered
        if entry and entry["status"] == "buffered":
            info = self.user_table.get((user, content_name))
            info["received"] += 1
            info["hop_count"] += entry["hop_count"]
            return True  # caller should immediately deliver

        # Case 2: already pending → aggregate
        if entry:
            entry["users"].add(user)
            return True

        # Case 3: first interest
        self.chunk_table[key] = {
            "users": {user},
            "status": "pending",
            "hop_count": 0
        }
        return False
          
    def start_user_request(self, user, content_name, total_chunks):
        self.user_table[(user, content_name)] = {
            "expected": total_chunks,
            "received": 0,
            "hop_count": 0.0
        }  
    def pop_users(self, content_name, byte_range):
        key = (content_name, byte_range)
        return self.table.pop(key, set())
        
    def chunk_arrived(self, content_name, byte_range, path):
        key = (content_name, byte_range)
        entry = self.chunk_table.get(key)
        if not entry:
            return {}

        users = entry["users"]
        entry["status"] = "buffered"
        entry["hop_count"] = len(path) - 1
        ready_users = defaultdict(float)
        users_to_remove = set()

        for user in users:
            ukey = (user, content_name)
            info = self.user_table.get(ukey)

            if info:
                info["received"] += 1
                info["hop_count"] += len(path) #- 1

                # Check if full content received
                if info["received"] >= info["expected"]:
                    ready_users[user] = info["hop_count"] / info["expected"]
                    del self.user_table[ukey]
                    users_to_remove.add(user)

        # Remove only completed users from this chunk entry
        users.difference_update(users_to_remove)

        # If nobody is waiting anymore → delete entire chunk entry
        if not users:
            del self.chunk_table[key]

        return ready_users





class Subscriber(Node):
    def __init__(self, node_id, coord, controller = None):
        super().__init__(node_id,False, coord)#review if erroneous
        self.path_exploration_table = []
        self.path_table = {}
        self.pending_interest_table = PendingInterestTable()
        self.exploration_over = False
        self.state = "INIT"
        self.controller = controller
        self.active_duration = 0  # check if all 4 needed here
        self.pending_requests = 0
        self.packet_loss_rate  = 0    # l''_t(m, s_k) ∈ [0,1]
        self.response_time  = 0
        self.lambda_ = 0.4
        self.connected_router = None

    def finish_path_selection(self, event_loop):
        self.state = "READY"
        debug_print(f"[{event_loop.time}] Edge {self.id} READY")
        self.controller.edge_ready(self.id, event_loop)

    def start_exploration(self, name, content_coord, event_loop, TM=10):
        self.state = "EXPLORING"
        debug_print(f"[{event_loop.time}] {self.id} Starting exploration...")
        for n in self.neighbors:
                event_loop.schedule(1, n.on_exploration_interest, Interest(name, path =[self]), event_loop, content_coord)

        event_loop.schedule(TM, self.on_exploration_timer_expire, name, event_loop, )

    def on_exploration_data(self, msg, event_loop):
        if self.state != "EXPLORING":
            debug_print (f"ooooooooooops {self.id} received exploration data({msg.name}) via path {msg.get_path()} but LATeeeeeeeeE")
            return
        debug_print(f"[{event_loop.time}] {self.id} received exploration Data({msg.name}) via path {msg.get_path()}")
        sk = msg.path[0:len(msg.path)//2+1]
        pathEntry = PathEntry(msg.name, sk)
        self.path_exploration_table.append(pathEntry) #(ak, sk)
        debug_print(f"[{event_loop.time}] {self.id} added entry !!! "+ "->".join(str(node.id) for node in sk))

    def on_exploration_timer_expire(self, name, event_loop):
        debug_print(f"[{event_loop.time}] {self.id} TM expired → selecting multipaths\n {name}")
        self.exploration_over = True
        # event_loop.stop_all_loops()
        debug_print(f"{self.id} PET")
        for entry  in self.path_exploration_table:
            debug_print(f"{entry.name} - lifetime, {entry.lifetime} {" -> ".join(str(node.id) for node in entry.path)}")
        # calculate path table.
        self.select_multipaths(event_loop)

    def select_multipaths(self, event_loop):
        self.state = "SELECTING"
        # group the path exploration table by content name and calculate weights
        grouped_paths = defaultdict(list)
        for entry in self.path_exploration_table:
            grouped_paths[entry.name].append(entry)

        for content_name, candidate_paths in grouped_paths.items():
            debug_print(f"Calculate path weight for content {content_name}")
            # 1. Compute path weights and caching nodeid
            for p in candidate_paths:
                p.weight = p.path_weight(candidate_paths)
            #calculate caching nodeid
            entry.cid = entry.path[1] #adding dummy caching nodeid

        # keep only the max weight entry in path_tab per provider
        path_tab, provider_map  = self.filter_entries()
        debug_print(f"Filtered path PET set")
        for entry  in path_tab:
            debug_print(f"{entry.name} : lifetime {entry.lifetime} ; weight {entry.weight} ; {" -> ".join(str(node.id) for node in entry.path)}")
        
        # remove low probability paths
        path_tab = [
            p for p in path_tab if p.weight >= 0.1 #todo: logic for pathweight threshold
        ]
        # Lines 15–25: remove overlapping paths
        selected = []
        for entry  in path_tab:
            pathEntry = PathEntry(entry.name, entry.path, entry.weight, cid= entry.path[-1])#adding dummy caching nodeid
            # self.path_table.append(pathEntry)
            self.path_table[pathEntry.key()] = pathEntry
            
        debug_print(f"initial path table")
        for entry  in self.path_table.values():
            debug_print(f"{entry.name} : lifetime {entry.lifetime} ; weight {entry.weight} ; cachingNode {entry.cid.id} {" -> ".join(str(node.id) for node in entry.path)}")
        
        for p in sorted(self.path_table.values(), key=lambda x: x.weight, reverse=True):#todo: check duplicates removed or not.
            conflict = False
            for s in selected:
                if self.path_overlap(p, s):
                    conflict = True
                    break
            if not conflict:
                selected.append(p)

        self.path_table.clear()

        for entry in selected:
            self.path_table[entry.key()] = entry
    
        #   group the path table by content name and calculate caching nodeid
        if utils.LMM == "LMM":
            grouped_paths = defaultdict(list)
            for name, entry in self.path_table.items():
                grouped_paths[name[0]].append(entry)
            # todo: find optimal caching policy.
            for content_name, candidate_paths in grouped_paths.items():
                debug_print(f"Calculate caching node for content {content_name}")
                #calculate caching nodeid
                filtered_nodes = {
                    node
                    for entry in candidate_paths
                    for node in entry.path
                    if not isinstance(node, Subscriber) and not node.is_publisher
                }

                caching_id= caching_decision(event_loop, self.coord, get_content_by_name(content_name), candidate_paths,filtered_nodes, 0, 5, 0 )
                for entry in candidate_paths:
                    entry.cid = caching_id
        debug_print(f"Final path table")
        for entry  in self.path_table.values():
            debug_print(f"{entry.name} : lifetime {entry.lifetime} ; weight {entry.weight}; cachingNode {entry.cid} ; {" -> ".join(str(node.id) for node in entry.path)}")

        self.state = "READY"
        debug_print(f"[{event_loop.time}] Edge {self.id} READY")
        self.controller.edge_ready(self.id, event_loop)

    def path_overlap(self, p1, p2):
        return (
            {n.id for n in p1.path if not isinstance(n, Subscriber)}
            &
            {n.id for n in p2.path if not isinstance(n, Subscriber)}
        )
 
    def filter_entries(self):

        provider_map = defaultdict(list)

        # Step 1: group by provider node
        for entry in self.path_exploration_table:
            provider = entry.path[-1]   # last node
            provider_map[provider].append(entry)

        result = []

        # Step 2: keep only max-weight entries per provider
        for provider, group in provider_map.items():
            max_weight = max(e.weight for e in group)
            debug_print(f"max weight is {max_weight} FOR PROVIDER {provider.id}")
            result.extend(e for e in group if e.weight == max_weight)

        return result, provider_map
     
    def on_user_data(self, msg, event_loop, source_id):
        # send data to users waiting if any
        # remove PIT entry
        users = self.pending_interest_table.chunk_arrived(msg.name, msg.byte_range, msg.path)
        if users:   # handles: key missing OR empty set/list
            for u, hops in users.items():
                event_loop.schedule(0, u.on_data, msg, event_loop, hops)
            # del self.pending_interest_table.table[msg.name]


    def on_user_interest(self, name, event_loop,source_node_id, user):

        # for all path entry pj for ak, 
        ## set sk to sj and cid to cidj
        ## send interst with ak, sk, cid

        debug_print(f"[{event_loop.time}] {self.id} xxxxxx received Interest({name} from {user.uid})")
        paths =[]
        for p in self.path_table.values():
            if p.name == name:
                paths.append(p)

        num_paths = len(paths)
        content_size = [c.size_kb * 1024 for c in CONTENT_LIST if c.name == name][0]
        ranges = self.compute_dynamic_chunks(content_size, num_paths)

        debug_print(f"[{event_loop.time}] EN {self.id} sends multichunk user Interests")
        self.pending_interest_table.start_user_request(user, name, num_paths)
        for pathentry, byte_range in zip(paths, ranges):
            # interest = Interest(name, byte_range, path.path.copy())
            # edge_node.forward_interest(interest, event_loop)
            if (not self.pending_interest_table.add_interest(name,byte_range, user)):
                interest = Interest(name,byte_range, pathentry.path, cid=pathentry.cid) #todo: logic for caching node_id, for now it is node
                next_hop = interest.path[1] # send request to second id. (EN -> SNx -> SNy).
                event_loop.schedule(1, next_hop.on_user_interest, interest, event_loop, self.id, user)
                debug_print(f"[{event_loop.time}] EN {self.id} sends user Interests to {interest.get_path()} via {next_hop.id}")
            else: # aggregation if request already pending
                debug_print(f"aggregated interests.. pls wait!!.")
        # start timer
        # on timer expire - do nothing ig?


    def compute_dynamic_chunks(self, content_size, num_paths):
        """
        Divide content into equal parts based on number of paths.
        """
        chunk_size = math.ceil(content_size / num_paths)
        ranges = []

        start = 0
        while start < content_size:
            end = min(start + chunk_size, content_size)
            ranges.append((start, end))
            start = end

        return ranges

    # def on_user_interest_original(self, name, event_loop,source_node_id, user):

    #     # for all path entry pj for ak, 
    #     ## set sk to sj and cid to cidj
    #     ## send interst with ak, sk, cid

    #     debug_print(f"[{event_loop.time}] {self.id} xxxxxx received Interest({name} from {user.uid})")
        
    #     if (not self.pending_interest_table.add_interest(name, user)):
    #         debug_print(f"[{event_loop.time}] EN {self.id} sends multipath user Interests")
    #         for p in self.path_table.values():
    #             if p.name == name:
    #                 interest = Interest(name, p.path, cid=p.cid) #todo: logic for caching node_id, for now it is node
    #                 next_hop = interest.path[1] # send request to second id. (EN -> SNx -> SNy).
    #                 event_loop.schedule(1, next_hop.on_user_interest, interest, event_loop, self.id, user)
    #                 debug_print(f"[{event_loop.time}] EN {self.id} sends user Interests to {interest.get_path()} via {next_hop.id}")
    #     else: # aggregation if request already pending
    #         debug_print(f"aggregated interests.. pls wait!!.")
    #     # start timer
    #     # on timer expire - do nothing ig?

    # def on_user_data_original(self, msg, event_loop, source_id):
    #     # send data to users waiting if any
    #     # remove PIT entry
    #     users = self.pending_interest_table.table.get(msg.name)
    #     if users:   # handles: key missing OR empty set/list
    #         for u in users:
    #             event_loop.schedule(0, u.on_data, msg, event_loop)
    #         del self.pending_interest_table.table[msg.name]
    # #start timer
    # # if not in explorationtable ___________
    # ### update path  by adding entry _______
    # ### calc path weight
    # ### create exploration entry? but when is this EE even used? except for creating/updating path table??
    # # else
    # ### calculate reward r(t+1)
    # ### calculate p(t+1)
    # ### update path table and cachingid
    # ############## no need to stop timer..............
    # EE_k = None
    # for ee in self.path_exploration_table:
    #     if ee.name == msg.name and ee.path[-1] == msg.path[-1]:
    #         EE_k = ee
    #         break
    # # Line 9–11: If EE_k is FALSE → create EE_k
    # groups = []
    # for p in self.path_exploration_table:
    #     if p.name == msg.name:
    #         groups.append(p)   
    # if EE_k is None:
    #     EE_k = PathEntry(msg.name, msg.path)

    #     EE_k.weight = EE_k.path_weight(EE_k, groups)

    #     self.exploration_table.append(EE_k)
    # # Line 12–15: Else → reward + update
    # else:
    #     current_path_weight = EE_k.path_weight(groups)
    #     r_t1  = EE_k.compute_reward(current_path_weight,True, 0.9)

    #     p_t1 = (
    #         (1 - self.lambda_) * EE_k.weight
    #         + self.lambda_ * (r_t1 + EE_k.weight)
    #     )

    #     EE_k.weight = p_t1
    #     key = EE_k.key()

    # if key in self.path_table:
    #     existing = self.path_table[key]

    #     # 🔁 Update fields (you control what is updated)
    #     existing.weight = EE_k.weight
    #     existing.lifetime = EE_k.lifetime
    #     existing.cid = EE_k.cid
    #     #EE_k.last_update_time = current_time

    #     # Update Path Table PT_i- paths alreadt updated

    #     # Update caching node ID
    #     #self.cID_k = self.select_caching_node(a_k)
    # debug_print(f"[{event_loop.time}] {self.id} received user Data({msg.name}) via path {msg.get_path()}")

    # # sk = msg.path[0:len(msg.path)//2+1]
    # # EE = ExplorationEntry(msg.name, sk)
    # # self.path_exploration_table.append(EE) #(ak, sk)
    # # debug_print(f"[{event_loop.time}] {self.id} added entry !!! "+ "->".join(str(node.id) for node in sk))
