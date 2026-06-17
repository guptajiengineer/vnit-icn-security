from node import *
from message import Interest
from collections import defaultdict
from pathUtils import PathEntry
from utils import debug_print
        
class PendingInterestTable:
    def __init__(self):
        self.table = {}

    def add_interest(self, content_name, user):
        if content_name in self.table:
            self.table[content_name].add(user)
            return True
        else:
            self.table[content_name] = {user}
            return False

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
            event_loop.schedule(1, n.on_exploration_interest, Interest(name, [self]), event_loop, content_coord)

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
            # 1. Compute path weights
            for p in candidate_paths:
                p.weight = p.path_weight(candidate_paths)

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
            pathEntry = PathEntry(entry.name, entry.path, entry.weight, cid= entry.path[1])#adding dummy caching nodeid
            # self.path_table.append(pathEntry)
            self.path_table[pathEntry.key()] = pathEntry
        debug_print(f"initial path table")
        for entry  in self.path_table.values():
            entry.cid = entry.path[1] #adding dummy caching nodeid
            debug_print(f"{entry.name} : lifetime {entry.lifetime} ; weight {entry.weight} ; cNode {entry.cid.id} {" -> ".join(str(node.id) for node in entry.path)}")
        
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

        debug_print(f"Final path table")
        for entry  in self.path_table.values():
            debug_print(f"{entry.name} : lifetime {entry.lifetime} ; weight {entry.weight} ; {" -> ".join(str(node.id) for node in entry.path)}")

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
        users = self.pending_interest_table.table.get(msg.name)
        if users:   # handles: key missing OR empty set/list
            for u in users:
                event_loop.schedule(0, u.on_data, msg, event_loop)
            del self.pending_interest_table.table[msg.name]

        #start timer
        # if not in explorationtable ___________
        ### update path  by adding entry _______
        ### calc path weight
        ### create exploration entry? but when is this EE even used? except for creating/updating path table??
        # else
        ### calculate reward r(t+1)
        ### calculate p(t+1)
        ### update path table and cachingid
        ############## no need to stop timer..............
        EE_k = None
        for ee in self.path_exploration_table:
            if ee.name == msg.name and ee.path[-1] == msg.path[-1]:
                EE_k = ee
                break
        # Line 9–11: If EE_k is FALSE → create EE_k
        groups = []
        for p in self.path_exploration_table:
            if p.name == msg.name:
                groups.append(p)   
        if EE_k is None:
            EE_k = PathEntry(msg.name, msg.path)

            EE_k.weight = EE_k.path_weight(EE_k, groups)

            self.exploration_table.append(EE_k)
        # Line 12–15: Else → reward + update
        else:
            current_path_weight = EE_k.path_weight(groups)
            r_t1  = EE_k.compute_reward(current_path_weight,True, 0.9)

            p_t1 = (
                (1 - self.lambda_) * EE_k.weight
                + self.lambda_ * (r_t1 + EE_k.weight)
            )

            EE_k.weight = p_t1
            key = EE_k.key()

        if key in self.path_table:
            existing = self.path_table[key]

            # 🔁 Update fields (you control what is updated)
            existing.weight = EE_k.weight
            existing.lifetime = EE_k.lifetime
            existing.cid = EE_k.cid
            #EE_k.last_update_time = current_time

            # Update Path Table PT_i- paths alreadt updated

            # Update caching node ID
            #self.cID_k = self.select_caching_node(a_k)
        debug_print(f"[{event_loop.time}] {self.id} received user Data({msg.name}) via path {msg.get_path()}")

        # sk = msg.path[0:len(msg.path)//2+1]
        # EE = ExplorationEntry(msg.name, sk)
        # self.path_exploration_table.append(EE) #(ak, sk)
        # debug_print(f"[{event_loop.time}] {self.id} added entry !!! "+ "->".join(str(node.id) for node in sk))


    def on_user_interest(self, name, event_loop,source_node_id, user):

        # for all path entry pj for ak, 
        ## set sk to sj and cid to cidj
        ## send interst with ak, sk, cid

        debug_print(f"[{event_loop.time}] {self.id} xxxxxx received Interest({name} from {user.uid})")
        
        if (not self.pending_interest_table.add_interest(name, user)):
            debug_print(f"[{event_loop.time}] EN {self.id} sends multipath user Interests")
            for p in self.path_table.values():
                if p.name == name:
                    interest = Interest(name, p.path, cid=p.cid) #todo: logic for caching node_id, for now it is node
                    next_hop = interest.path[1] # send request to second id. (EN -> SNx -> SNy).
                    event_loop.schedule(1, next_hop.on_user_interest, interest, event_loop, self.id, user)
                    debug_print(f"[{event_loop.time}] EN {self.id} sends user Interests to {interest.get_path()} via {next_hop.id}")
        else: # aggregation if request already pending
            debug_print(f"aggregated interests.. pls wait!!.")
        # start timer
        # on timer expire - do nothing ig?

