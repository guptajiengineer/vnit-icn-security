# content.py

class Content:
    def __init__(self, name, size_kb, generation_time, lifespan=10000000, popularity=1.0):
        self.name = name                  # a_k
        self.size_kb = size_kb
        self.generation_time = generation_time  # g(a_k)
        self.lifespan = lifespan                # t'(a_k)
        self.popularity = popularity
        self.data = None

    def age(self, current_time):
        """t_c - g(a_k)"""
        return current_time - self.generation_time

    def normalized_lifespan(self, current_time):
        """
        f(a_k) from eq (15):
        (t_c - g(a_k)) / t'(a_k) if >= T_k else 0
        """
        age = self.age(current_time)
        if age >= 0:
            return age / self.lifespan
        return 0

    def is_alive(self, current_time):
        """Whether content is still valid"""
        return True
        return self.age(current_time) <= self.lifespan

    def __repr__(self):
        return (f"Content({self.name}, gen={self.generation_time}, "
                f"life={self.lifespan})")
def get_content_by_name(name):
    return next((c for c in CONTENT_LIST if c.name == name), None)

    
# global_contents

CONTENT_LIST = [
    Content("C1_VideoStream", 1500, generation_time=0, lifespan=120, popularity=0.9),
    Content("C2_MapTiles", 800, generation_time=10, lifespan=200, popularity=0.7),
    Content("C3_SensorData", 300, generation_time=20, lifespan=80, popularity=0.5),
    Content("C4_SoftwareUpdate", 2500, generation_time=5, lifespan=300, popularity=0.3),
]
