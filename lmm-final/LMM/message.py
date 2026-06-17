from pathUtils import *
from typing import List, Dict
import time

class Interest:
    def __init__(self, name, path=None, cid = 0):
        self.name = name
        self.path = path or []
        self.cid = cid
    def get_path(self):
        return "->".join(str(node.id) for node in self.path)

class Data:
    def __init__(self, name, path, cid = 0, content = None):
        self.name = name
        self.content = content
        self.path = path
        self.cid = cid
    def get_path(self):
        return "->".join(str(node.id) for node in self.path)
    
class Content:
    def __init__(self, name, generation_time, lifespan):
        self.name = name                # a_k
        self.generation_time = generation_time  # g(a_k)
        self.lifespan = lifespan        # t'(a_k)
