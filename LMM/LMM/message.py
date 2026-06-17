# =============================
# Message packets
# =============================
class Interest:
    def __init__(self, name, path=None):
        self.name = name
        self.path = path or []
    def get_path(self):
        return " -> ".join(str(node.id) for node in self.path)

class Data:
    def __init__(self, name, path):
        self.name = name
        self.path = path
    def get_path(self):
        return " -> ".join(str(node.id) for node in self.path)