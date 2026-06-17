
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
\




def setup_network_with_multipaths(num_routers=5, num_publishers=3, num_subscribers=1, use_saved=True, seed = None):
    """
    Setup network with:
    - Variable number of ROUTERS (user input)
    - Variable number of PUBLISHERS (user input)
    - Variable number of SUBSCRIBERS (user input)
    - Multiple paths between routers
    """
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
    if seed is not None:
        random.seed(seed)

    base_radius=12
    jitter=2.5
    extra_links=5
    # ---------------------
    # Routers: even + random
    # ---------------------
    for i in range(num_routers):
        angle = (2 * math.pi * i / num_routers) + random.uniform(-0.25, 0.25)
        radius = base_radius + random.uniform(-jitter, jitter)
        routers.append(
                Router(
                    node_id=f"R{i+1}",
                    has_content=False,
                    coord=Coordinates(
                        radius * math.cos(angle),
                        radius * math.sin(angle)
                        ),
                    resources=resources
                )
            )
    # ---------------------
    # Ensure connectivity
    # ---------------------
    shuffled = routers[:]
    random.shuffle(shuffled)

    for i in range(len(shuffled) - 1):
        shuffled[i].connect(shuffled[i + 1])

    # ---------------------
    # Random router links
    # ---------------------
    for _ in range(extra_links):
        a, b = random.sample(routers, 2)
        a.connect(b)

    # ---------------------
    # Publishers
    # ---------------------
    publishers = []
    for i in range(num_publishers):
        
        # p = Publisher(f"P{i+1}")
        r = random.choice(routers)
        p = Router(
                node_id=f"P{i+1}",
                has_content=True,
                coord=Coordinates(
                    r.coord.x + random.uniform(-1.5, 1.5),
                    r.coord.y + random.uniform(-1.5, 1.5)
                ),
                resources=resources
            )
        p.connect(r)
        publishers.append(p)

    # ---------------------
    # Subscribers
    # ---------------------
    subscribers = []
    for i in range(num_subscribers):
        # s = Subscriber(f"S{i+1}")
        r = random.choice(routers)
        s = Subscriber(
                node_id=f"S{i+1}",
                coord=Coordinates(
                    r.coord.x + random.uniform(-1.5, 1.5),
                    r.coord.y + random.uniform(-1.5, 1.5)
                )
            )
        s.connect(r)
        subscribers.append(s)

    save_network(routers, publishers, subscribers)
    debug_print(f"Created network with {num_routers} routers, {num_publishers} publishers, and {num_subscribers} subscribers.")
    debug_print(f"Network setup saved.\n")
    return routers, publishers, subscribers
