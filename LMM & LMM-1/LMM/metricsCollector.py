
from utils import debug_print
class MetricsCollector:
    def __init__(self):
        self.records = []  # list of dicts

    def record(self, user_id, run_id, hops, duration):
        self.records.append({
            "user": user_id,
            "run": run_id,
            "hops": hops,
            "duration": duration
        })

    def average_per_user(self):
        stats = {}
        for r in self.records:
            u = r["user"]
            stats.setdefault(u, {"hops": [], "duration": []})
            stats[u]["hops"].append(r["hops"])
            stats[u]["duration"].append(r["duration"])

        return {
            u: {
                "avg_hops": sum(v["hops"]) / len(v["hops"]),
                "avg_duration": sum(v["duration"]) / len(v["duration"])
            }
            for u, v in stats.items()
        }

    def overall_average(self):
        hops = [r["hops"] for r in self.records]
        durations = [r["duration"] for r in self.records]

        return {
            "avg_hops": sum(hops) / len(hops) if hops else 0,
            "avg_duration": sum(durations) / len(durations) if durations else 0
        }
    
    def print_records(self):
        if not self.records:
            print("No metrics recorded.")
            return

        print("\n========== RECORDED METRICS ==========\n")
        print(f"{'Run':<6} {'User':<12} {'Hops':<6} {'Duration':<10}")
        print("-" * 38)

        for r in self.records:
            print(
                f"{r['run']:<6} "
                f"{r['user']:<12} "
                f"{r['hops']:<6} "
                f"{r['duration']:<10.2f}"
            )

        print("\n=====================================\n")
        
