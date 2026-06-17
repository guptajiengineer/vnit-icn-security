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
import utils #import utils.debug_print, CACHEHIT
import utils
import numpy as np

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

    SN2   = Router("SN2", True, Coordinates(4, -4), is_publisher=True)
    SN2p  = Router("SN2'", False, Coordinates(0, -5))
    SN2pp = Router("SN2''", True, Coordinates(-4, -4), is_publisher=True)

    SN3 = Router("SN3", True, Coordinates(0,-8), is_publisher=True)  # producer

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

    utils.debug_print(sn.node_weight())

    # Edge Node
    EN0 = Subscriber("EN0", Coordinates(0, 0))

    # Service Nodes
    SN1   = Router("SN1", False, Coordinates(2, -2), resources = resources)
    SN2   = Router("SN2", False, Coordinates(3, -3), resources = resources)
    SN3   = Router("SN3", False, Coordinates(4, -4), resources = resources)
    SN4   = Router("SN4", False, Coordinates(5, -5), resources = resources)
    SN5   = Router("SN5", True, Coordinates(6, -6), resources = resources, is_publisher = True)

    BN1  = Router("BN1", False, Coordinates(0, -2), resources = resources)
    BN2  = Router("BN2", False, Coordinates(0, -5), resources = resources)
    BN3  = Router("BN3", False, Coordinates(0, -8), resources = resources)
    BN4  = Router("BN4", False, Coordinates(0, -10), resources = resources)
    BN5  = Router("BN5", False, Coordinates(0, -14), resources = resources)
    BN6 = Router("BN6", True, Coordinates(0,-16), resources = resources, is_publisher = True) 

    PN1 = Router("PN1", False, Coordinates(-3, -3), resources = resources)
    PN2 = Router("PN2", False, Coordinates(-4, -4), resources = resources)
    PN3 = Router("PN3", False, Coordinates(-7, -7), resources = resources)
    PN4 = Router("PN4", True, Coordinates(-8, -8), resources = resources, is_publisher = True)

    TN1 = Router("TN1", False, Coordinates(1, -2), resources = resources)
    TN2 = Router("TN2", False, Coordinates(1.5, -4), resources = resources)
    TN3 = Router("TN3", True, Coordinates(2, -6), resources = resources, is_publisher = True)
    

    QN1 = Router("QN1", False, Coordinates(-1.5, -2.5), resources = resources)
    QN2 = Router("QN2", False, Coordinates(-2, -4.5), resources = resources)
    QN3 = Router("QN3", False, Coordinates(-3.5, -7.5), resources = resources)
    QN4 = Router("QN4", True, Coordinates(-4, -8), resources = resources, is_publisher = True)

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


def get_network_120_realistic(num_publishers=6):
    resources = [
        Resource("CPU", remaining=80, threshold=30),
        Resource("Cache", remaining=500, threshold=100),
        Resource("Bandwidth", remaining=50, threshold=20),
    ]

    routers = []
    publishers = []
    subscribers = []

    # ---------- 1. CORE BACKBONE (12 routers in circle) ----------
    core = []
    core_radius = 10
    for i in range(12):
        angle = 2 * math.pi * i / 12
        x = core_radius * math.cos(angle)
        y = core_radius * math.sin(angle)

        r = Router(f"C{i}", False, Coordinates(x, y), resources=resources)
        core.append(r)
        routers.append(r)

    # fully interconnect core (backbone mesh)
    for i in range(len(core)):
        for j in range(i + 1, len(core)):
            core[i].connect(core[j])
            core[j].connect(core[i])

    # ---------- 2. AGGREGATION CLUSTERS (6 clusters) ----------
    agg_clusters = []
    cluster_radius = 35

    for k in range(6):
        angle = 2 * math.pi * k / 6
        cx = cluster_radius * math.cos(angle)
        cy = cluster_radius * math.sin(angle)

        cluster = []
        for i in range(14):  # 6 * 14 = 84 routers
            offset_angle = 2 * math.pi * i / 14
            x = cx + 6 * math.cos(offset_angle)
            y = cy + 6 * math.sin(offset_angle)

            r = Router(f"A{k}_{i}", False, Coordinates(x, y), resources=resources)
            cluster.append(r)
            routers.append(r)

        # ring inside cluster
        for i in range(14):
            a = cluster[i]
            b = cluster[(i + 1) % 14]
            a.connect(b)
            b.connect(a)

        # connect cluster to 2 core routers
        core1 = core[k * 2]
        core2 = core[(k * 2 + 1) % 12]
        for r in cluster[:3]:
            r.connect(core1)
            core1.connect(r)
        for r in cluster[3:6]:
            r.connect(core2)
            core2.connect(r)

        agg_clusters.append(cluster)

    # ---------- 3. EDGE CHAINS (off aggregation) ----------
    edge_count = 120 - len(routers)  # remaining routers
    edge_per_cluster = edge_count // 6

    for k, cluster in enumerate(agg_clusters):
        base = cluster[0]
        prev = base

        for i in range(edge_per_cluster):
            x = prev.coord.x + 4
            y = prev.coord.y - 4

            r = Router(f"E{k}_{i}", False, Coordinates(x, y), resources=resources)
            routers.append(r)

            prev.connect(r)
            r.connect(prev)

            prev = r

    # ---------- 4. Subscribers at extreme edges ----------
    for i in range(6):
        sub = Subscriber(f"EN{i}", Coordinates(0, 0))
        edge_router = routers[-(i+1)]
        sub.connect(edge_router)
        edge_router.connect(sub)
        subscribers.append(sub)

    # ---------- 5. Publishers in core/aggregation ----------
    pub_candidates = core[:4] + [cluster[7] for cluster in agg_clusters]
    for i in range(min(num_publishers, len(pub_candidates))):
        pub = pub_candidates[i]
        routers.remove(pub)
        pub.is_publisher = True
        pub.has_content = True
        publishers.append(pub)

    return routers, publishers, subscribers

def debug_print_network(nodes):
    for node in nodes:
        utils.debug_print(node.id, node.coord.__repr__(), "neigh", " ".join(str(n.id) for n in node.neighbors))
        utils.debug_print(f"{node.active_duration} {node.pending_requests}  {node.packet_loss_rate}  {node.response_time}")

def get_user_input():
    """Get all network parameters from user"""
    utils.debug_print("\n" + "="*70)
    utils.debug_print("MULTIPATH CDN SIMULATOR - NETWORK CONFIGURATION")
    utils.debug_print("="*70 + "\n")
    
    # Get number of routers
    while True:
        try:
            num_routers = int(input("Enter number of routers (minimum 3): "))
            if num_routers >= 3:
                break
            utils.debug_print("Please enter at least 3 routers.")
        except ValueError:
            utils.debug_print("Invalid input. Please enter a number.")

    # Get number of publishers
    while True:
        try:
            num_publishers = int(input("Enter number of publishers (minimum 1): "))
            if num_publishers >= 1:
                break
            utils.debug_print("Please enter at least 1 publisher.")
        except ValueError:
            utils.debug_print("Invalid input. Please enter a number.")

    # Get number of subscribers
    while True:
        try:
            num_subscribers = int(input("Enter number of subscribers (minimum 1): "))
            if num_subscribers >= 1:
                break
            utils.debug_print("Please enter at least 1 subscriber.")
        except ValueError:
            utils.debug_print("Invalid input. Please enter a number.")

    # Get number of iterations
    while True:
        try:
            iterations = int(input("Enter number of iterations (minimum 10): "))
            if iterations >= 10:
                break
            utils.debug_print("Please enter at least 10 iterations.")
        except ValueError:
            utils.debug_print("Invalid input. Please enter a number.")

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
        utils.debug_print(f"Adjusted routers to: {num_routers}")
    
    if num_publishers < 1:
        num_publishers = 1
        utils.debug_print(f"Adjusted publishers to: {num_publishers}")
    
    if num_subscribers < 1:
        num_subscribers = 1
        utils.debug_print(f"Adjusted subscribers to: {num_subscribers}")

    utils.debug_print(f"\n=== NETWORK CONFIGURATION ===")
    utils.debug_print(f"Routers: {num_routers}")
    utils.debug_print(f"Publishers: {num_publishers}")
    utils.debug_print(f"Subscribers: {num_subscribers}")
    utils.debug_print(f"================================\n")
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
            resources=resources,
            is_publisher=True
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
        utils.debug_print(f"Failed to load network: {e}")
        return None


def get_network_120_mesh(num_publishers=6, spacing_x=3, spacing_y=3, add_diagonals=True):
    """
    12x10 mesh network (120 routers)
    No isolated branches.
    Coordinates match topology exactly.
    """

    resources = [
        Resource("CPU", remaining=80, threshold=30),
        Resource("Cache", remaining=500, threshold=100),
        Resource("Bandwidth", remaining=50, threshold=20),
    ]

    # rows = 10
    # cols = 12
    rows = 5
    cols = 5

    routers = []
    grid = {}

    # ---- Create routers on grid ----
    for r in range(rows):
        for c in range(cols):
            node_id = f"R_{r}_{c}"
            coord = Coordinates(c * spacing_x, -r * spacing_y)

            router = Router(node_id, False, coord, resources=resources)
            routers.append(router)
            grid[(r, c)] = router

    # ---- Connect neighbors (mesh) ----
    for r in range(rows):
        for c in range(cols):
            current = grid[(r, c)]

            # Right
            if c + 1 < cols:
                right = grid[(r, c + 1)]
                current.connect(right)
                right.connect(current)

            # Down
            if r + 1 < rows:
                down = grid[(r + 1, c)]
                current.connect(down)
                down.connect(current)

            # Diagonals (optional, improves centrality behavior)
            if add_diagonals:
                if r + 1 < rows and c + 1 < cols:
                    diag = grid[(r + 1, c + 1)]
                    current.connect(diag)
                    diag.connect(current)

                if r + 1 < rows and c - 1 >= 0:
                    diag = grid[(r + 1, c - 1)]
                    current.connect(diag)
                    diag.connect(current)

    # ---- Subscribers at meaningful positions ----
    subscribers = [
        Subscriber("EN0", grid[(0, 0)].coord),
        Subscriber("EN1", grid[(0, cols-1)].coord),
        Subscriber("EN2", grid[(rows-1, 0)].coord),
        Subscriber("EN3", grid[(rows-1, cols-1)].coord),
        Subscriber("EN4", grid[(rows//2, 0)].coord),
        Subscriber("EN5", grid[(rows//2, cols-1)].coord),
    ]

    # Connect subscribers to nearest routers
    sub_positions = [(0,0),(0,cols-1),(rows-1,0),(rows-1,cols-1),(rows//2,0),(rows//2,cols-1)]
    # sub_positions = [(0,0)]
    for sub, pos in zip(subscribers, sub_positions):
        router = grid[pos]
        sub.connect(router)
        router.connect(sub)

    # ---- Publishers (farthest spread nodes) ----
    publisher_positions = [
        (rows//2, cols//2),
        (0, cols//2),
        (rows-1, cols//2),
        (rows//2, cols//3),
        (rows//2, 2*cols//3),
        (rows//3, cols//2),
    ]
    publisher_positions = [(2, 2), (0, 2), (3, 2), (2, 1), (2, 0), (1, 2)]

    publishers = []
    for i in range(min(num_publishers, len(publisher_positions))):
        r, c = publisher_positions[i]
        pub = grid[(r, c)]
        routers.remove(pub)
        pub.is_publisher = True
        pub.has_content = True
        publishers.append(pub)

    return routers, publishers, subscribers


def main():
    
    utils.DEBUG = False
    loop = EventLoop()
    # num_routers, num_publishers, num_subscribers, iterations = get_user_input()
    num_routers = 20
    num_publishers = 4
    num_subscribers = 1
    num_runs_per_setting = 50
    seed_start = 100 # arbitrary
    seed_end = seed_start + num_runs_per_setting
    # provider_results = {p: {"hops", "duration"} for p in [4, 6, 8, 10]}
    provider_results = {}
    usecase = [ "LMM", "LMM-1"]
    for lmm in usecase:
        utils.LMM = lmm
        for num_publishers in [4, 6, 8, 10]:
            utils.debug_print(f"\n=== Running experiments for providers = {num_publishers} ===")
            metrics = MetricsCollector()
            for seed in range(seed_start, seed_end):
                utils.debug_print(f"  → Seed = {seed}")
                # Setup network
                routers, publishers, subscribers = setup_network_with_multipaths1( #get_network_120_realistic(num_publishers)
                    num_routers,
                    num_publishers,
                    num_subscribers,
                    use_saved=True,
                    seed = seed
                )

                # 2. Reset / create simulation components
                loop = EventLoop()
    
                network = routers + publishers + subscribers
                initialize_node_metrics(network, seed=9 )  # change seed → reproducible experiments
                debug_print_network(network)
                # plot_network(network, "spring")
                utils.debug_print("\nplotted\n")
                utils.debug_print("\nAll nodes initialized and running\n")
                # metrics = MetricsCollector()
                user = User("U1", [subscribers[0]], metrics, 20)
                user2 = User("U2", [subscribers[0]], metrics, 20)
                user3 = User("U3", [subscribers[0]], metrics, 20)
                user4 = User("U4", [subscribers[0]], metrics, 20)
                user5 = User("U5", [subscribers[0]], metrics, 20)
                user6 = User("U6", [subscribers[0]], metrics, 20)
                user7 = User("U7", [subscribers[0]], metrics, 20)
                user8 = User("U8", [subscribers[0]], metrics, 20)
                user9 = User("U9", [subscribers[0]], metrics, 20)
                users = [user, user2, user3,  user4, user5, user6, user7, user8, user9]
                simulationController = SimulationController(loop,subscribers, [user, user2])
                for i, EN in enumerate(subscribers):
                    EN.controller = simulationController
                    EN.start_exploration(
                        "C2_MapTiles",
                        publishers[random.randint(0, num_publishers - 1)].coord,
                        loop,
                        20
                    )
                
                poll_for_user_ready(users, loop)
                # poll_for_user_ready(user2, loop)
                # loop.schedule(28, user2.request, "C2_MapTiles", loop)
                loop.run()

                # 4. print metrics
            print_metrics(metrics)

            overall = metrics.overall_average()

            if num_publishers not in provider_results:
                provider_results[num_publishers] = {}
            provider_results[num_publishers][lmm] = {
                    "avg_hops": overall["avg_hops"],
                    "avg_duration": overall["avg_duration"]
                }
    plot_metrics(provider_results)

def plot_metrics(provider_results):
    print(utils.CACHEHIT)
    num_publishers_list = sorted(provider_results.keys())

    # Extract metrics for plotting
    avg_hops_caching = [provider_results[n]["LMM"]["avg_hops"] for n in num_publishers_list]
    avg_hops_no_cache = [provider_results[n]["LMM-1"]["avg_hops"] for n in num_publishers_list]
    # avg_hops_hybrid = [provider_results[n]["hybrid"]["avg_hops"] for n in num_publishers_list]
    
    avg_duration_caching = [provider_results[n]["LMM"]["avg_duration"] for n in num_publishers_list]
    avg_duration_no_cache = [provider_results[n]["LMM-1"]["avg_duration"] for n in num_publishers_list]


    x = np.arange(len(num_publishers_list))  # positions
    width = 0.25  # width of each bar

    fig, ax = plt.subplots(figsize=(10,6))

    ax.bar(x - width, avg_hops_no_cache, width, label='LMM-1 (Without Caching)')
    ax.bar(x, avg_hops_caching, width, label='LMM-3 (Caching)')
    # ax.bar(x + width, avg_hops_hybrid, width, label='Hybrid')

    ax.set_xticks(x)
    ax.set_xticklabels(num_publishers_list)
    ax.set_xlabel("Number of Publishers")
    ax.set_ylabel("Average Hops")
    ax.set_title("Average Hops for Different Use Cases")
    ax.legend()

    plt.show() 
    x = np.arange(len(num_publishers_list))  # positions
    width = 0.25  # width of each bar

    fig, ax = plt.subplots(figsize=(10,6))

    ax.bar(x - width, avg_duration_no_cache, width, label='LMM-1 (Without Caching)')
    ax.bar(x , avg_duration_caching, width, label='LMM-3 (Caching)')
    # ax.bar(x + width, avg_hops_hybrid, width, label='Hybrid')

    ax.set_xticks(x)
    ax.set_xticklabels(num_publishers_list)
    ax.set_xlabel("Number of Publishers")
    ax.set_ylabel("Average Duration")
    ax.set_title("Average Duration for Different Use Cases")
    ax.legend()

    plt.show()


    # providers = list(provider_results.keys())
    # avg_hops = [provider_results[p]["avg_hops"] for p in providers]
    # avg_durations = [provider_results[p]["avg_duration"] for p in providers]
    # plt.figure()
    # bars = plt.bar(providers, avg_hops)
    # plt.xlabel("Number of Providers")
    # plt.ylabel("Average Hops")
    # plt.title("Average Hops vs Number of Providers")
    # plt.ylim(bottom=0)   # 👈 start from zero
    # plt.grid(axis='y')
    # plt.show()
    # # 👇 annotate bars?
    # plt.figure()
    # plt.bar(providers, avg_durations)
    # plt.xlabel("Number of Providers")
    # plt.ylabel("Average delay")
    # plt.title("Average delay vs Number of Providers")
    # plt.ylim(bottom=0)   # 👈 start from zero
    # plt.grid(axis='y')
    # plt.show()


def print_metrics(metrics):
    metrics.print_records()
    print("Per-user averages:")
    print(metrics.average_per_user())

    print("\nOverall average:")
    print(metrics.overall_average())
    # print(f"{loop.time}")

def poll_for_user_ready(users, event_loop):
    
    # wait for user to be enabled to start requesting
    if users[0].isEnabled == True:
        users[0].request("C2_MapTiles", event_loop)
        users[1].request("C2_MapTiles", event_loop)
        # print(f"enabled @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@{event_loop.time}")
        event_loop.schedule(10, users[2].request, "C2_MapTiles",  event_loop)
        event_loop.schedule(12, users[3].request, "C2_MapTiles",  event_loop)
        event_loop.schedule(33, users[4].request, "C2_MapTiles",  event_loop)
        event_loop.schedule(41, users[5].request, "C2_MapTiles",  event_loop)
        event_loop.schedule(51, users[6].request, "C2_MapTiles",  event_loop)
        # event_loop.schedule(20, poll_for_user_ready,users,  event_loop)

    else:
        event_loop.schedule(1, poll_for_user_ready,users,  event_loop)

def main1():
    
    utils.DEBUG = True
    loop = EventLoop()
    # num_routers, num_publishers, num_subscribers, iterations = get_user_input()
    num_routers = 20
    num_publishers = 6
    num_subscribers = 1
    num_runs_per_setting = 100
    metrics = MetricsCollector()
    # seed = 100 
    # print(f"\n=== Running experiments for providers = {num_publishers} ===")
    # print(f"  → Seed = {seed}")
    # Setup network
    # routers, publishers, subscribers = setup_network_with_multipaths1(
    #     num_routers,
    #     num_publishers,
    #     num_subscribers,
    #     use_saved=True,
    #     seed = seed
    # )
    # routers, publishers, subscribers = get_network_120_mesh()
    # routers, publishers, subscribers = get_network_120_realistic()
    routers, publishers, subscribers = get_network1()

    network = routers + publishers + subscribers
    initialize_node_metrics(network)
    debug_print_network(network)
    plot_network(network, "spring")
    plot_network(network)
    utils.debug_print("\nplotted\n")
    utils.debug_print("\nAll nodes initialized and running\n")
    user = User("U1", [subscribers[0]], metrics, 20)
    user2 = User("U2", [subscribers[0]], metrics, 20)
    user3 = User("U3", [subscribers[0]], metrics, 20)
    user4 = User("U4", [subscribers[0]], metrics, 20)
    user5 = User("U5", [subscribers[0]], metrics, 20)
    users = [user, user2, user3,  user4, user5]
    simulationController = SimulationController(loop,subscribers, [user, user2])
    ran_pub = random.randint(0, num_publishers - 1)
    for i, EN in enumerate(subscribers):
        EN.controller = simulationController
        EN.start_exploration(
            "C2_MapTiles",
            publishers[ran_pub].coord,
            loop,
            20
        )
    
    poll_for_user_ready(users, loop)
    # poll_for_user_ready(user2, loop)
    loop.run()
    print_metrics(metrics)
    overall = metrics.overall_average()
    metrics.print_records()

if __name__ == "__main__":
    main()