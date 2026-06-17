class PathEntry:
    def __init__(self, name, path, weight = 0, lifetime = 7, cid = None):
        self.name = name      # a_k
        self.path = tuple(path)           # s_k (IMMUTABLE) (list of node IDs)
        self.weight = weight
        self.lifetime = lifetime
        self.cid = cid     #caching ID
        self.active = True
    def key(self):
        return (self.name, self.path)

    def avg_connection_duration(self):
        total = sum(node.active_duration for node in self.path)
        return total / len(self.path)
    
    def normalized_duration(self, all_paths):
        d_prime = self.avg_connection_duration()
        d_primes = [p.avg_connection_duration() for p in all_paths]
        return d_prime / (max(d_primes) + min(d_primes))

    def avg_pending_requests(self):
        total = sum(node.pending_requests for node in self.path)
        return total / len(self.path)
    
    def normalized_pending_requests(self, all_paths):
        q_prime = self.avg_pending_requests()
        q_primes = [p.avg_pending_requests() for p in all_paths]
        denom = max(1, max(q_primes)) + min(q_primes)
        return q_prime / denom
    
    def avg_packet_loss(self):
        return sum(node.packet_loss_rate for node in self.path) / len(self.path)
    
    def normalized_packet_loss(self, all_paths):
        l_prime = self.avg_packet_loss()
        l_primes = [p.avg_packet_loss() for p in all_paths]
        denom = max(1, max(l_primes)) + min(l_primes)
        return l_prime / denom
    
    def avg_response_time(self):
        return sum(node.response_time for node in self.path) / len(self.path)
    
    def normalized_response_time(self, all_paths):
        o_prime = self.avg_response_time()
        o_primes = [p.avg_response_time() for p in all_paths]
        denom = max(1, max(o_primes)) + min(o_primes)
        return o_prime / denom
    
    def update_packet_loss(self):
        utilization = self.pending_requests / max(1, self.capacity)
        self.packet_loss_rate = min(1.0, 0.01 + utilization * 0.1)

    def update_response_time(self):
        self.response_time = (
            self.base_processing_time *
            (1 + self.pending_requests / max(1, self.capacity))
        )

    def path_weight(self, all_paths):
        d = self.normalized_duration(all_paths)
        q = self.normalized_pending_requests(all_paths)
        l = self.normalized_packet_loss(all_paths)
        o = self.normalized_response_time(all_paths)
        return d / (q + l + o)

    def compute_reward(self, current_path_weight, content_received: bool, sigma: float):
        """
        Implements Eq. (13)
        """
        sign = 1 if content_received else -1
        return sign * sigma * current_path_weight
    
    def update_path_weight(p_t: float, reward: float, lambda_: float = 0.2):
        """
        Implements Eq. (12)
        """
        return p_t + lambda_ * reward
    
    def update_path_after_event(self, all_paths, content_received: bool, lambda_: float = 0.2, sigma: float = 1.0):
        """
        Called at time t+1 when:
        - Data is received OR
        - Timer expires
        """
        # recompute normalized metrics at t+1
        d = self.normalized_duration(all_paths)
        q = self.normalized_pending_requests(all_paths)
        l = self.normalized_packet_loss(all_paths)
        o = self.normalized_response_time(all_paths)

        # reward
        r = self.compute_reward(d_t1=d, q_t1=q, l_t1=l, o_t1=o, content_received=content_received, sigma=sigma )

        # update weight
        self.path.weight = self.update_path_weight(
            p_t=self.path.weight,
            reward=r,
            lambda_=lambda_
        )
        return self.path.weight
