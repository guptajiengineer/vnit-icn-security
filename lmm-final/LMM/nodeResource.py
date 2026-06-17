from dataclasses import dataclass

# @dataclass
class Resource:
    name: str
    remaining: float   # v(i,j)
    threshold: float   # RT(i,j)
    
    def __init__(self, name, remaining, threshold):
        self.name = name
        self.remaining = remaining
        self.threshold = threshold

    def weight(self) -> float:
        if self.remaining > self.threshold:
            return self.remaining / self.threshold
        return 0.0
