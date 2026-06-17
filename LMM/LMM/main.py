from node import Node
from eventLoop import EventLoop
from user import User
from serviceNode import ServiceNode
from edgeNode import EdgeNode
from coordinates import Coordinates
import networkx as nx
import matplotlib.pyplot as plt


def plot_network(nodes, layout="coordinates"):
    """
    Generic network visualization utility.

    nodes  : list of Node objects
    layout : spring | kamada_kawai | circular | shell
    """

    G = nx.Graph()

    # Build graph generically
    for node in nodes:
        G.add_node(node.id, is_edge=isinstance(node, EdgeNode), has_content=node.has_content)
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


# # =============================
# # Network Builder
# # =============================
# def build_network(num_edges, num_services):
#     edges = [Node(f"EN{i}", is_edge=True) for i in range(num_edges)]
#     services = [
#         Node(f"SN{i}", cache=(i % 2 == 0), has_content=(i == num_services - 1))
#         for i in range(num_services)
#     ]

#     # Connect ENs to all SNs
#     for en in edges:
#         en.connect(*services)

#     # Fully connect SNs (multipath)
#     for sn in services:
#         sn.connect(*services)

#     return edges, services

def get_network():
    """
    Builds the exact network shown in Fig. 2 for debugging
    """

    # Edge Node
    EN0 = EdgeNode("EN0", Coordinates(0, 1))

    # Service Nodes
    SN1   = ServiceNode("SN1", False, Coordinates(2, -2))
    SN1p  = ServiceNode("SN1'", False, Coordinates(0, -2))
    SN1pp = ServiceNode("SN1''", False, Coordinates(-3, -3))

    SN2   = ServiceNode("SN2", True, Coordinates(4, -4))
    SN2p  = ServiceNode("SN2'", False, Coordinates(0, -5))
    SN2pp = ServiceNode("SN2''", True, Coordinates(-4, -4))

    SN3 = ServiceNode("SN3", True, Coordinates(0,-8))  # producer

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

    # Edge Node
    EN0 = EdgeNode("EN0", Coordinates(0, 0))

    # Service Nodes
    SN1   = ServiceNode("SN1", False, Coordinates(2, -2))
    SN2   = ServiceNode("SN2", False, Coordinates(3, -3))
    SN3   = ServiceNode("SN3", False, Coordinates(4, -4))
    SN4   = ServiceNode("SN4", False, Coordinates(5, -5))
    SN5   = ServiceNode("SN5", True, Coordinates(6, -6))

    BN1  = ServiceNode("BN1", False, Coordinates(0, -2))
    BN2  = ServiceNode("BN2", False, Coordinates(0, -5))
    BN3  = ServiceNode("BN3", False, Coordinates(0, -8))
    BN4  = ServiceNode("BN4", False, Coordinates(0, -10))
    BN5  = ServiceNode("BN5", False, Coordinates(0, -14))
    BN6 = ServiceNode("BN6", True, Coordinates(0,-16)) 

    PN1 = ServiceNode("PN1", False, Coordinates(-3, -3))
    PN2 = ServiceNode("PN2", False, Coordinates(-4, -4))
    PN3 = ServiceNode("PN3", False, Coordinates(-7, -7))
    PN4 = ServiceNode("PN4", True, Coordinates(-8, -8))

    TN1 = ServiceNode("TN1", False, Coordinates(1, -2))
    TN2 = ServiceNode("TN2", False, Coordinates(1.5, -4))
    TN3 = ServiceNode("TN3", True, Coordinates(2, -6))
    

    QN1 = ServiceNode("QN1", False, Coordinates(-1.5, -2.5))
    QN2 = ServiceNode("QN2", False, Coordinates(-2, -4.5))
    QN3 = ServiceNode("QN3", False, Coordinates(-3.5, -7.5))
    QN4 = ServiceNode("QN4", False, Coordinates(-4, -8))

    # Connections (bidirectional)
    EN0.connect(SN1, BN1, PN1, TN1, QN1)

    SN1.connect(EN0, SN2)
    SN2.connect(SN1, SN3)
    SN3.connect(SN2, SN4)
    SN4.connect(SN3, SN5)
    SN5.connect(SN4)

    
    BN1.connect(EN0, BN2)
    BN2.connect(BN1, BN3)
    BN3.connect(BN2, BN4)
    BN4.connect(BN3, BN5)
    BN5.connect(BN4, BN6)
    BN6.connect(BN5)

    PN1.connect(EN0, PN2)
    PN2.connect(PN1, PN3)
    PN3.connect(PN2, PN4)
    PN4.connect(PN3)

    TN1.connect(EN0, TN2)
    TN2.connect(TN1, TN3)
    TN3.connect(TN2)

    QN1.connect(EN0, QN2)
    QN2.connect(QN1, QN3)
    QN3.connect(QN2, QN4)
    QN4.connect(QN3)

    nodes = [
        EN0,
        SN1,SN2,SN3,SN4, SN5,
        BN1, BN2, BN3, BN4, BN5, BN6,
        PN1, PN2, PN3, PN4,
        TN1, TN2, TN3,
        QN1, QN2, QN3, QN4
    ]

    return nodes, EN0

def print_network(nodes):
    for node in nodes:
        print(node.id, "neigh", " ".join(str(n.id) for n in node.neighbors))
# =============================
# MAIN
# =============================
def main():
    loop = EventLoop()

    # num_edges = int(input("Enter number of Edge Nodes: "))
    # num_services = int(input("Enter number of Service Nodes: "))

    # edges, services = build_network(num_edges, num_services)
    network, EN = get_network1()
    print_network(network)
    print("\nAll nodes initialized and running\n")

    user = User("U1", EN)
    # user.request("a1", loop)
    plot_network(network)
    print("\nplotted\n")
    EN.start_exploration("a1", Coordinates(0, -16), loop, 20)

    loop.run()

if __name__ == "__main__":
    main()