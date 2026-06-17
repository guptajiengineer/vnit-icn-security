import math
from message import *
from node import *
from edgeNode import Subscriber
from typing import List, Dict
from utils import debug_print

class Router(Node):
    def __init__(self, node_id, has_content, coord, weight=1, resources = None):
        super().__init__(node_id, has_content, coord)
        self.weight = weight
        self.cache = set()
        self.pending_interest_table = [] #list of content names
        self.resources = resources  # list[Resource]
        self.active_duration = 0  # increases while path is active
        self.pending_requests = 0
        self.packet_loss_rate  = 0    # l''_t(m, s_k) ∈ [0,1]
        self.response_time  = 0
        self.contents = {}

    def node_weight(self) -> float:
        w = 1.0
        for r in self.resources:
            w_j = r.weight()
            if w_j == 0:
                return 0.0
            w *= w_j
        return w
    
    def consume(self, resource_name, amount):
        for r in self.resources:
            if r.name == resource_name:
                r.remaining = max(0, r.remaining - amount)
    
    def recover_resources(self):
        for r in self.resources:
            r.remaining += r.threshold * 0.1  # 10% recovery

    def on_exploration_interest(self, msg, event_loop, content_coord):
        debug_print(f"[{event_loop.time}] {self.id} received Interest({msg.name}) via path {msg.get_path()}")
        prev_node = msg.path[-1]#last node of path set sk
        # if self.coord.distance_to(content_coord) >= prev_node.coord.distance_to(content_coord):#todo..debug
        #     return

        msg.path.append(self)

        # if msg.name in self.cache:
        if self.has_content:#send data with ak, sk along sk path
            # data = Data(msg.name, msg.path.copy())# todo: retrieve from cache
            event_loop.schedule(1, prev_node.on_exploration_data, Data(msg.name, msg.path.copy()), event_loop)
            return

        if self.node_weight() > 0:            
            if (msg.name not in self.pending_interest_table):
                debug_print(f"[{event_loop.time}] {self.id} sends multipath exploration Interests as weight >0 (={self.node_weight()})")
            for n in self.neighbors:
                if n not in msg.path:#avoids infinite loop
                   event_loop.schedule(1, n.on_exploration_interest, Interest(msg.name, msg.path.copy()), event_loop, content_coord)
        
    def on_exploration_data(self, data, event_loop):
        debug_print(f"[{event_loop.time}] {self.id} received exploration Data({data.name}) via path {data.get_path()}")
        # get nodeiId of the the prev node in datapath
        # get node & call on_data.
        # self.paths.append(data.path_set)
        idx = data.path.index(self)
        data.path.append(self)
        event_loop.schedule(1, data.path[idx - 1].on_exploration_data, Data(data.name, data.path.copy()), event_loop)
 

    def on_user_interest(self, interest, event_loop, source_node_id, user):
        # interest = Interest(name)
        debug_print(f"[{event_loop.time}] {self.id} received User Interest({interest.name} path {interest.get_path()})")
        # if it has data
        ##send ak, sk, and ck
        ##return
        if self.has_content:
            debug_print(f"[{event_loop.time}] {self.id} csays:i have data {interest.name}")
            for n in self.neighbors :
                # if n.id != source_node_id:
                    event_loop.schedule(1, n.on_user_data, Data(interest.name, interest.path), event_loop, self.id)#todo:correct data
                    debug_print(f"[{event_loop.time}] {self.id} user data sent to {interest.name} - {n.id}")
            return
        
        #if SN in sk and no PIT entry for ak (i.e if SN not in sk -> ignore broadcasting)
        ## sreate PIT entry
        ##forward interest 
        # aggregation if request already pending
        if (self.id in  {n.id for n in interest.path}) and interest.name not in self.pending_interest_table:
            debug_print(f"[{event_loop.time}] {self.id} got a user interest {interest.name} which it is forwarding")
            self.pending_interest_table.append(interest.name)
            self.pending_requests +=1
            for n in self.neighbors:
                # if not isinstance(n , EdgeNode):
                if n.id != source_node_id: #forward to all except the source
                    event_loop.schedule(1, n.on_user_interest, interest, event_loop, self.id, user)
                    debug_print(f"[{event_loop.time}] {self.id} user interest sent to {interest.name} - {n.id}")
        elif interest.name in self.pending_interest_table:
            debug_print(f"{event_loop.time}] {self.id} Already waiting for {interest.name}")
        elif self.id in  {n.id for n in interest.path}:
            self.pending_requests +=1
        else:            
            debug_print(f"[{event_loop.time}] {self.id} oops the user interet {interest.name} not my concern")

    def on_user_data(self, msg, event_loop, source_node_id):
        if(self.id == msg.cid):
            #todo: cache
            debug_print(f"CAACCCHHHHEEEEEEDDDDDDD")
            debug_print(f"[{event_loop.time}] {self.id} got a user data {msg.name} which it is forwarding")

            debug_print(f"[{event_loop.time}] {self.id} checking PIT {msg.name}: {self.pending_interest_table}")
        if(msg.name in self.pending_interest_table):
            
            debug_print(f"[{event_loop.time}] {self.id} found in  PIT {msg.name}")
            for n in self.neighbors:
                if n.id != source_node_id: #forward to all except the source
                    event_loop.schedule(1, n.on_user_data, msg, event_loop, self.id)
                    debug_print(f"[{event_loop.time}] {self.id} sent user data {msg.name} to {n.id}")
            self.pending_interest_table.remove(msg.name)
            self.pending_requests +=1
