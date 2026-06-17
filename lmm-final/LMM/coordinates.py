# coordinates.py
class Coordinates:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def distance_to(self, other: "Coordinates") -> float:
        return ((self.x - other.x)**2 + (self.y - other.y)**2) ** 0.5

    def __repr__(self):
        return f"Coordinates(x={self.x}, y={self.y})"
