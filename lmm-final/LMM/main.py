from node import Node
from eventLoop import EventLoop
from user import User
from serviceNode import Router
from edgeNode import Subscriber
from coordinates import Coordinates
import networkx as nx
import matplotlib.pyplot as plt
from nodeResource import Resource
from simulationController import SimulationController
import random
import os
import pickle
import math
from metricsCollector import MetricsCollector
from utils import debug_print
import utils


utils.DEBUG = True


def plot_network(nodes, layout="coordinates"):
    """
    Generic network visualization utility.

    nodes  : list of Node objects
    layout : spring | kamada_kawai | circular | shell
    """
    G = nx.Graph()
    # Build graph generically
    for node in nodes:
        G.add_node(node.id, is_edge=isinstance(node, Subscriber), has_content=node.has_content)
        for nbr in node.neighbors:
            G.add_edge(node.id, nbr.id)

    if layout == "coordinates":
        pos = {
            node.id: (node.coord.x, node.coord.y)
            for node in nodes
        }
    elif layout == "spring":
        pos = nx.spring_layout(G, seed=42)
    elif layout == "kamada_kawai":
        pos = nx.kamada_kawai_layout(G)
    elif layout == "circular":
        pos = nx.circular_layout(G)
    elif layout == "shell":
        pos = nx.shell_layout(G)
    else:
        raise ValueError("Unknown layout type")

    # Node coloring (generic)
    node_colors = []
    for n in G.nodes(data=True):
        if n[1].get("is_edge"):
            node_colors.append("#125175")  # blue
        elif n[1].get("has_content"):
            node_colors.append("#74c476")  # green
        else:
            node_colors.append("#d9d9d9")  # gray

    plt.figure(figsize=(9, 7))
    nx.draw(
        G,
        pos,
        with_labels=True,
        node_size=1800,
        node_color=node_colors,
        font_size=10,
        font_weight="bold",
        edge_color="#999999"
    )

    plt.title("Multipath Exploration Network")
    plt.axis("off")
    plt.show()

def initialize_node_metrics(
    nodes,
    seed = 9,
    conn_duration_range=(10.0, 11.0),   # seconds
    pending_req_range=(0, 2),            # count
    packet_loss_range=(0.0, 0.1),         # probability
    response_time_range=(20.0, 32.0)     # milliseconds
):
    """
    Assigns seeded random initial metrics to all nodes.
    """

    random.seed(seed)
    for node in nodes:
        node.active_duration = random.uniform(
            *conn_duration_range
        )

        node.pending_requests = random.randint(
            *pending_req_range
        )

        node.packet_loss = random.uniform(
            *packet_loss_range
        )

        node.response_time = random.uniform(
            *response_time_range
        )

        for node in nodes:
            node.active_duration = 10

            node.pending_requests = 0

            node.packet_loss = 0

            node.response_time = 2

def get_network():
    """
    Builds the exact network shown in Fig. 2 for debugging
    """

    # Edge Node
    EN0 = Subscriber("EN0", Coordinates(0, 1))

    # Service Nodes
    SN1   = Router("SN1", False, Coordinates(2, -2))
    SN1p  = Router("SN1'", False, Coordinates(0, -2))
    SN1pp = Router("SN1''", False, Coordinates(-3, -3))

    SN2   = Router("SN2", True, Coordinates(4, -4))
    SN2p  = Router("SN2'", False, Coordinates(0, -5))
    SN2pp = Router("SN2''", True, Coordinates(-4, -4))

    SN3 = Router("SN3", True, Coordinates(0,-8))  # producer

    # Connections (bidirectional)
    EN0.connect(SN1, SN1p, SN1pp)

    SN1.connect(EN0, SN2)
    SN1p.connect(EN0, SN2p)
    SN1pp.connect(EN0, SN2pp)

    SN2.connect(SN1)
    SN2p.connect(SN1p, SN3)
    SN2pp.connect(SN1pp)

    SN3.connect(SN2p)

    nodes = [
        EN0,
        SN1, SN1p, SN1pp,
        SN2, SN2p, SN2pp,
        SN3
    ]

    return nodes, EN0


def get_network1():
    """
    Builds the exact network shown in Fig. 2 for debugging
    """
    resources = [
        Resource("CPU", remaining=80, threshold=30),
        Resource("Cache", remaining=500, threshold=100),
        Resource("Bandwidth", remaining=50, threshold=20),
    ]

    sn = Router("SNx", False, Coordinates(2, -2), resources = resources)

    debug_print(sn.node_weight())

    # Edge Node
    EN0 = Subscriber("EN0", Coordinates(0, 0))

    # Service Nodes
    SN1   = Router("SN1", False, Coordinates(2, -2), resources = resources)
    SN2   = Router("SN2", False, Coordinates(3, -3), resources = resources)
    SN3   = Router("SN3", False, Coordinates(4, -4), resources = resources)
    SN4   = Router("SN4", False, Coordinates(5, -5), resources = resources)
    SN5   = Router("SN5", True, Coordinates(6, -6), resources = resources)

    BN1  = Router("BN1", False, Coordinates(0, -2), resources = resources)
    BN2  = Router("BN2", False, Coordinates(0, -5), resources = resources)
    BN3  = Router("BN3", False, Coordinates(0, -8), resources = resources)
    BN4  = Router("BN4", False, Coordinates(0, -10), resources = resources)
    BN5  = Router("BN5", False, Coordinates(0, -14), resources = resources)
    BN6 = Router("BN6", True, Coordinates(0,-16), resources = resources) 

    PN1 = Router("PN1", False, Coordinates(-3, -3), resources = resources)
    PN2 = Router("PN2", False, Coordinates(-4, -4), resources = resources)
    PN3 = Router("PN3", False, Coordinates(-7, -7), resources = resources)
    PN4 = Router("PN4", True, Coordinates(-8, -8), resources = resources)

    TN1 = Router("TN1", False, Coordinates(1, -2), resources = resources)
    TN2 = Router("TN2", False, Coordinates(1.5, -4), resources = resources)
    TN3 = Router("TN3", True, Coordinates(2, -6), resources = resources)
    

    QN1 = Router("QN1", False, Coordinates(-1.5, -2.5), resources = resources)
    QN2 = Router("QN2", False, Coordinates(-2, -4.5), resources = resources)
    QN3 = Router("QN3", False, Coordinates(-3.5, -7.5), resources = resources)
    QN4 = Router("QN4", True, Coordinates(-4, -8), resources = resources)

    # Connections (bidirectional)
    EN0.connect(SN1)
    EN0.connect( BN1)
    EN0.connect( PN1 )
    EN0.connect(TN1)
    EN0.connect(QN1)

    SN1.connect(EN0)
    SN1.connect(SN2)
    
    SN2.connect( SN3)
    SN2.connect(SN1)
    SN3.connect(SN2)
    SN3.connect(SN4)
    SN4.connect(SN3)
    SN4.connect(SN5)
    SN5.connect(SN4)

    
    BN1.connect(EN0)
    BN1.connect(BN2)
    BN2.connect(BN1)
    BN2.connect(BN3)
    BN3.connect(BN2)
    BN3.connect(BN4)
    BN4.connect(BN5)
    BN4.connect(BN3)
    BN5.connect( BN6)
    BN5.connect(BN4)
    BN6.connect(BN5)

    PN1.connect(EN0)
    PN1.connect(PN2)
    PN2.connect(PN1)
    PN2.connect( PN3)
    PN3.connect(PN2)
    PN3.connect(PN4)
    PN4.connect(PN3)

    TN1.connect(EN0)
    TN1.connect(TN2)
    TN2.connect(TN1)
    TN2.connect(TN3)
    TN3.connect(TN2)

    QN1.connect(EN0)
    QN1.connect(QN2)
    QN2.connect(QN3)
    QN2.connect(QN1)
    QN3.connect(QN4)
    QN3.connect(QN2)
    QN4.connect(QN3)

    nodes = [
        EN0,
        SN1,SN2,SN3,SN4, SN5,
        BN1, BN2, BN3, BN4, BN5, BN6,
        PN1, PN2, PN3, PN4,
        TN1, TN2, TN3,
        QN1, QN2, QN3, QN4
    ]
    routers = [
        
        SN1,SN2,SN3,SN4, 
        BN1, BN2, BN3, BN4, BN5,
        PN1, PN2, PN3, 
        TN1, TN2, 
        QN1, QN2, QN3
    ]
    publishers= [
         SN5, BN6, PN4, TN3, QN4
    ]
    subscribers= [
        EN0
    ]
    return routers, publishers, subscribers

def debug_print_network(nodes):
    for node in nodes:
        debug_print(node.id, "neigh", " ".join(str(n.id) for n in node.neighbors))
        debug_print(f"{node.active_duration} {node.pending_requests}  {node.packet_loss_rate}  {node.response_time}")

def get_user_input():
    """Get all network parameters from user"""
    debug_print("\n" + "="*70)
    debug_print("MULTIPATH CDN SIMULATOR - NETWORK CONFIGURATION")
    debug_print("="*70 + "\n")
    
    # Get number of routers
    while True:
        try:
            num_routers = int(input("Enter number of routers (minimum 3): "))
            if num_routers >= 3:
                break
            debug_print("Please enter at least 3 routers.")
        except ValueError:
            debug_print("Invalid input. Please enter a number.")

    # Get number of publishers
    while True:
        try:
            num_publishers = int(input("Enter number of publishers (minimum 1): "))
            if num_publishers >= 1:
                break
            debug_print("Please enter at least 1 publisher.")
        except ValueError:
            debug_print("Invalid input. Please enter a number.")

    # Get number of subscribers
    while True:
        try:
            num_subscribers = int(input("Enter number of subscribers (minimum 1): "))
            if num_subscribers >= 1:
                break
            debug_print("Please enter at least 1 subscriber.")
        except ValueError:
            debug_print("Invalid input. Please enter a number.")

    # Get number of iterations
    while True:
        try:
            iterations = int(input("Enter number of iterations (minimum 10): "))
            if iterations >= 10:
                break
            debug_print("Please enter at least 10 iterations.")
        except ValueError:
            debug_print("Invalid input. Please enter a number.")

    return num_routers, num_publishers, num_subscribers, iterations

def setup_network_with_multipaths1(num_routers=5, num_publishers=3, num_subscribers=1, use_saved=True, seed = None):

    if use_saved and os.path.exists("Saved_Network/network_setup.pkl"):
        # choice = input("Use existing network? (yes/no): ").strip().lower()
        choice = "no"
        if choice == 'yes':
            routers, publishers, subscribers  = load_network()
            return routers, publishers, subscribers

    # Validate inputs
    if num_routers < 3:
        num_routers = 3
        debug_print(f"Adjusted routers to: {num_routers}")
    
    if num_publishers < 1:
        num_publishers = 1
        debug_print(f"Adjusted publishers to: {num_publishers}")
    
    if num_subscribers < 1:
        num_subscribers = 1
        debug_print(f"Adjusted subscribers to: {num_subscribers}")

    debug_print(f"\n=== NETWORK CONFIGURATION ===")
    debug_print(f"Routers: {num_routers}")
    debug_print(f"Publishers: {num_publishers}")
    debug_print(f"Subscribers: {num_subscribers}")
    debug_print(f"================================\n")
    # router is same as publisher except for has_content value is true in publisher
    # Create routers
    #routers = [Router(f'Router{i+1}') for i in range(num_routers)]
    
    resources = [
        Resource("CPU", remaining=80, threshold=30),
        Resource("Cache", remaining=500, threshold=100),
        Resource("Bandwidth", remaining=50, threshold=20),
    ]
    
    subscribers = []
    routers = []
    publishers = []   
    
    base_radius=12
    jitter=2.5
    extra_link_ratio: float = 0.2
    random.seed(100)
    # Place routers in noisy ring
    for i in range(num_routers):
        angle = 2 * math.pi * i / num_routers
        angle += random.uniform(-0.25, 0.25)
        radius = base_radius + random.uniform(-jitter, jitter)

        routers.append(
            Router(
                node_id=f"R{i}",
                has_content=False,
                coord=Coordinates(
                    radius * math.cos(angle),
                    radius * math.sin(angle)
                ),
                resources=resources
            )
        )
    attach_degree = 2

    # Ensure connectivity (ring)
    for i in range(num_routers):
        routers[i].connect(routers[(i + 1) % num_routers])

    # Add random shortcuts
    extra_links = int(extra_link_ratio * num_routers)
    for _ in range(extra_links):
        a, b = random.sample(routers, 2)
        a.connect(b)

    
    for i in range(num_subscribers):
        r = random.choice(routers)

        s = Subscriber(
            node_id=f"S{i}",
            coord=Coordinates(
                r.coord.x + random.uniform(-1.5, 1.5),
                r.coord.y + random.uniform(-1.5, 1.5)
            )
        )

        s.connect(r)
    subscribers.append(s)

    random.seed(seed)
    for i in range(num_publishers):
        attach_points = random.sample(routers, attach_degree)

        p = Router(
            node_id=f"P{i}",
            has_content=True,
            coord=Coordinates(
                sum(r.coord.x for r in attach_points) / attach_degree,
                sum(r.coord.y for r in attach_points) / attach_degree
            ),
            resources=resources
        )

        for r in attach_points:
            p.connect(r)
        publishers.append(p)
        
    return routers, publishers, subscribers

def save_network(routers, publishers, subscribers):
    """Save network configuration"""
    os.makedirs("Saved_Network", exist_ok=True)
    with open("Saved_Network/network_setup.pkl", "wb") as file:
        pickle.dump((routers, publishers, subscribers), file)

def load_network():
    """Load saved network configuration"""
    try:
        with open("Saved_Network/network_setup.pkl", "rb") as file:
            file = pickle.load(file)
            return file
    except Exception as e:
        debug_print(f"Failed to load network: {e}")
        return None
    

def main():
    
    utils.DEBUG = False
    loop = EventLoop()
    # num_routers, num_publishers, num_subscribers, iterations = get_user_input()
    num_routers = 20
    num_publishers = 4
    num_subscribers = 1
    num_runs_per_setting = 100
    seed_start = 100 # arbitrary
    seed_end = seed_start + num_runs_per_setting
    provider_results = {p: {"hops", "duration"} for p in [4, 6, 8, 10]}
    for num_publishers in [4, 6, 8, 10]:
        print(f"\n=== Running experiments for providers = {num_publishers} ===")
        metrics = MetricsCollector()
        for seed in range(seed_start, seed_end):
            print(f"  → Seed = {seed}")
            # Setup network
            # routers, publishers, subscribers = setup_network_with_multipaths1(
            #     num_routers,
            #     num_publishers,
            #     num_subscribers,
            #     use_saved=True,
            #     seed = seed
            # )
            routers, publishers, subscribers = get_network1()
            # 2. Reset / create simulation components
            loop = EventLoop()
  
            network = routers + publishers + subscribers
            initialize_node_metrics(network, seed=9 )  # change seed → reproducible experiments
            debug_print_network(network)
            # plot_network(network, "spring")
            debug_print("\nplotted\n")
            debug_print("\nAll nodes initialized and running\n")
            # metrics = MetricsCollector()
            user = User("U1", subscribers, metrics, 20)
            user2 = User("U2", subscribers, metrics, 20)
            simulationController = SimulationController(loop,subscribers, [user, user2])
            for i, EN in enumerate(subscribers):
                EN.controller = simulationController
                EN.start_exploration(
                    "a1",
                    publishers[random.randint(0, num_publishers - 1)].coord,
                    loop,
                    20
                )
            
            poll_for_user_ready(user, loop)
            poll_for_user_ready(user2, loop)
            # loop.schedule(28, user2.request, "a1", loop)
            loop.run()

            # 4. print metrics
        print_metrics(metrics)

        overall = metrics.overall_average()


        provider_results[num_publishers] = {
                "avg_hops": overall["avg_hops"],
                "avg_duration": overall["avg_duration"]
            }
    plot_metrics(provider_results)

def plot_metrics(provider_results):
    providers = list(provider_results.keys())
    avg_hops = [provider_results[p]["avg_hops"] for p in providers]
    avg_durations = [provider_results[p]["avg_duration"] for p in providers]
    plt.figure()
    bars = plt.bar(providers, avg_hops)
    plt.xlabel("Number of Providers")
    plt.ylabel("Average Hops")
    plt.title("Average Hops vs Number of Providers")
    plt.ylim(bottom=0)   #  start from zero
    plt.grid(axis='y')
    plt.show()
    #  annotate bars?
    plt.figure()
    plt.bar(providers, avg_durations)
    plt.xlabel("Number of Providers")
    plt.ylabel("Average delay")
    plt.title("Average delay vs Number of Providers")
    plt.ylim(bottom=0)   #  start from zero
    plt.grid(axis='y')
    plt.show()


def print_metrics(metrics):
    metrics.print_records()
    print("Per-user averages:")
    print(metrics.average_per_user())

    print("\nOverall average:")
    print(metrics.overall_average())
    # print(f"{loop.time}")

def poll_for_user_ready(user, event_loop):
    
    # wait for user to be enabled to start requesting
    if user.isEnabled == True:
        user.request("a1", event_loop)
    else:
        event_loop.schedule(1, poll_for_user_ready,user,  event_loop)
def main1():
    
    utils.DEBUG = True
    loop = EventLoop()
    # num_routers, num_publishers, num_subscribers, iterations = get_user_input()
    num_routers = 20
    num_publishers = 4
    num_subscribers = 1
    num_runs_per_setting = 100
    seed = 100 
    print(f"\n=== Running experiments for providers = {num_publishers} ===")
    metrics = MetricsCollector()
    print(f"  → Seed = {seed}")
    # Setup network
    # routers, publishers, subscribers = setup_network_with_multipaths1(
    #     num_routers,
    #     num_publishers,
    #     num_subscribers,
    #     use_saved=True,
    #     seed = seed
    # )
    routers, publishers, subscribers = get_network1()

    network = routers + publishers + subscribers
    initialize_node_metrics(network)
    debug_print_network(network)
    plot_network(network)
    debug_print("\nplotted\n")
    debug_print("\nAll nodes initialized and running\n")
    user = User("U1", subscribers, metrics, 20)
    user2 = User("U2", subscribers, metrics, 20)
    simulationController = SimulationController(loop,subscribers, [user, user2])
    for i, EN in enumerate(subscribers):
        EN.controller = simulationController
        EN.start_exploration(
            "a1",
            publishers[random.randint(0, num_publishers - 1)].coord,
            loop,
            20
        )
    
    poll_for_user_ready(user, loop)
    poll_for_user_ready(user2, loop)
    loop.run()
    print_metrics(metrics)
    overall = metrics.overall_average()
    metrics.print_records()

if __name__ == "__main__":
    main1()