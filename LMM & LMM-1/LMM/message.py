from pathUtils import *
from typing import List, Dict
import time

class Interest:
    def __init__(self, name, byte_range = None, path=None, chunk_id=-1, cid = 0):
        self.name = name
        # self.chunk_id = chunk_id 
        self.path = path or []
        self.cid = cid
        self.byte_range = byte_range  # (start, end)

    def get_path(self):
        return "->".join(str(node.id) for node in self.path)

class Data:
    def __init__(self, name, path, byte_range = None, payload = None, cid = 0, content = None, chunk_id=-1):
        self.name = name
        # self.chunk_id = chunk_id
        self.content = content
        self.byte_range = byte_range
        self.payload = payload
        self.path = path
        self.cid = cid
    def get_path(self):
        return "->".join(str(node.id) for node in self.path)
