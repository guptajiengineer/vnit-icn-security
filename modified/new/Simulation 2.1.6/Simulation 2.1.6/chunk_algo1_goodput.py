# Addition for main2.py based on Algorithm 1 and Goodput Formula (from PDF)

# --- Insert the following logic (full, real code) ---

import numpy as np

class MultiPathChunkDistributor:
    """
    Implements Algorithm 1 with Goodput formula assignment for multi-path chunk distribution.
    """
    def __init__(self, arrival_time_table, consumer_send_time, chunk_size, num_chunks, smooth_c=0.2):
        """
        :param arrival_time_table: dict, path -> list of arrival times [float]
        :param consumer_send_time: float
        :param chunk_size: int/float (bytes)
        :param num_chunks: int
        :param smooth_c: float (smoothing factor c in [0,1])
        """
        self.arrival_time_table = arrival_time_table
        self.consumer_send_time = consumer_send_time
        self.chunk_size = chunk_size
        self.num_chunks = num_chunks
        self.smooth_c = smooth_c
        self.paths = list(arrival_time_table.keys())
        self.num_paths = len(self.paths)
        self.smooth_goodputs = {path: 0.0 for path in self.paths}

    def calculate_forward_delays(self, arrival_times):
        return [t - self.consumer_send_time for t in arrival_times]

    def calculate_path_goodput(self, delays):
        # Goodput = chunk_size / delay
        return [self.chunk_size/d if d > 0 else 0.0 for d in delays]

    def smooth_goodput(self, path, inst_goodput):
        prev_g = self.smooth_goodputs[path]
        smoothed = (1-self.smooth_c)*prev_g + self.smooth_c*inst_goodput
        self.smooth_goodputs[path] = smoothed
        return smoothed

    def distribute_chunks(self):
        # Calculate delays and instantaneous goodput for each path (using first arrival time)
        inst_delays = [self.calculate_forward_delays(self.arrival_time_table[path])[0] for path in self.paths]
        inst_goodputs = self.calculate_path_goodput(inst_delays)
        # Update EWMA (smoothed) goodput
        for path, g in zip(self.paths, inst_goodputs):
            self.smooth_goodput(path, g)
        # Use smoothed goodput as weights
        weights = [self.smooth_goodputs[path] for path in self.paths]
        sum_w = sum(weights)
        allocation = [int(np.floor((w/sum_w)*self.num_chunks)) for w in weights]
        remainder = self.num_chunks - sum(allocation)
        # Distribute the remainder
        while remainder > 0:
            fracs = [((w/sum_w)*self.num_chunks) - a for w, a in zip(weights, allocation)]
            idx = np.argmax(fracs)
            allocation[idx] += 1
            remainder -= 1
        allocations = {path: allocation[i] for i, path in enumerate(self.paths)}
        return allocations
