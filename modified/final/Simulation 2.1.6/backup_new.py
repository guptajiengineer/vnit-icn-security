import os
import random
import datetime
import time
import collections
import csv
import networkx as nx
import matplotlib.pyplot as plt
import pickle  # Import pickle for saving and loading
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import pickle


class MLPolicy:
    def __init__(self, model_path='ml_models/random_forest_policy_selector.pkl'):
        with open(model_path, 'rb') as f:
            self.model = pickle.load(f)

    def predict_best_policy(self, features):
        # Convert features into a DataFrame (this is what the model expects)
        df = pd.DataFrame([features])
        # Predict the best policy based on current features
        label = self.model.predict(df)[0]
        return ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR'][label]  # Map back to policy name


# Base classes for Network elements
class Node:
    def __init__(self, name):
        self.name = name
        self.fib = {}  # Forwarding Information Base
        self.pit = {}  # Pending Interest Table
        self.cs = []   # Content Store with limited cache size (15 images)

class InterestPacket:
    def __init__(self, name):
        self.name = name
        self.nonce = random.randint(1000, 9999)
        self.visited = set()
        self.path = []
        self.original_hop_count = 0 
        self.actual_hop_count = 0  

class DataPacket:
    def __init__(self, name, content):
        self.name = name
        self.content = content

class ContentIDManager:
    _content_id_map = {}
    
    @classmethod
    def initialize_index(cls, publishers):
        """Initialize index for all images across publishers"""
        image_id = 100  # Starting ID range from 100
        for publisher in publishers:
            for image_name in publisher.images.keys():
                if image_name not in cls._content_id_map:
                    cls._content_id_map[image_name] = image_id
                    image_id += 1
    
    @classmethod
    def get_unique_id(cls, content_name):
        """Retrieve the unique ID for a given content name."""
        return cls._content_id_map.get(content_name, None)
    
# Router class with caching policies and FIB, PIT, CS functionality
class Router(Node):
    CACHE_LIMIT = 15  # Cache size limit
    TOP_N_POPULAR = 5  # Reserve top 5 for most popular items

    def __init__(self, name, caching_policy='LRU', alpha=0.9):
        super().__init__(name)
        self.caching_policy = caching_policy  # Store the caching policy
        self.alpha = alpha  # Smoothing factor for EWMA (for calculating popularity)
        self.popularity_table = pd.DataFrame(columns=['Content Name', 'R_count', 'Popularity', 'Rank', 'Feedback'])
        self.cache_frequency = collections.defaultdict(int)  # Frequency for LFU policy
        self.cache_access_times = {}  # Access times for LRU and MRU policies
        self.connections = []  # Store connections to other routers or nodes
        self.fib={}
        self.reset()  # Initialize or reset all internal state variables

        self.save_fib()  #save initial fib
        

    def reset(self):
        """Reset the router's cache, tables, and statistics."""
        self.cache_hits = 0  
        self.publisher_hits = 0  
        self.requests_served_from_cache = 0
        self.requests_served_from_publisher = 0
        self.cache_evictions = 0  
        self.cache_access_times = {}  # Store the last access time for cache entries (for LRU/MRU)
        self.cache_frequency = collections.defaultdict(int)  # Frequency of accesses (for LFU)
        self.total_cache_access_time = 0  
        self.total_requests = 0  
        self.content_popularity = collections.defaultdict(int)  # Track how often each content is requested
        self.cache_ttl = {}  # Store time-to-live (TTL) for cache entries
        self.cs = []  # Clear the content store (cache)
        self.pit = {}  # Clear the pending interest table (PIT)


    def update_popularity(self, content_name, feedback=None):
        """Update the request count and popularity score for content based on requests and feedback."""
        # Check if the content already exists in the popularity table
        if content_name in self.popularity_table['Content Name'].values:
            # Update existing entry
            content_index = self.popularity_table[self.popularity_table['Content Name'] == content_name].index[0]
            current_popularity = self.popularity_table.at[content_index, 'Popularity']
            r_count = self.popularity_table.at[content_index, 'R_count'] + 1

            # Adjust popularity based on feedback
            feedback_weights = {'highly_like': 1.5,'like': 1.2,'neutral': 1.0,'dislike': 0.8,'highly_dislike': 0.5} # Weights for feedback
            adjustment = feedback_weights.get(feedback, 1)  # Default adjustment is 1 (no feedback)

            # Apply EWMA with feedback adjustment
            new_popularity = self.alpha * current_popularity + (1 - self.alpha) * r_count * adjustment
            self.popularity_table.at[content_index, 'R_count'] = r_count
            self.popularity_table.at[content_index, 'Popularity'] = new_popularity
            self.popularity_table.at[content_index, 'Feedback'] = feedback or 'None'
        else:
            # Add new content entry with initial values if it doesn't exist
            new_entry = {
            'Content Name': content_name,
            'R_count': 1,
            'Popularity': (1 - self.alpha),
            'Rank': None,  # Rank will be updated later
            'Feedback': feedback or 'None'
            }
            self.popularity_table = pd.concat([self.popularity_table, pd.DataFrame([new_entry])], ignore_index=True)
            
        # Re-rank content after updating popularity
        self.rank_content()

 
    def rank_content(self):
        """Rank contents based on their popularity scores as integers and limit decimal points."""
        # Rank in descending order of popularity, converting rank to integers
        self.popularity_table['Rank'] = self.popularity_table['Popularity'].rank(method='min', ascending=False).astype(int)
    
        # Round the 'Popularity' column to 4 decimal places
        self.popularity_table['Popularity'] = pd.to_numeric(self.popularity_table['Popularity'], errors='coerce').round(4)
    
        # Sort values by rank
        self.popularity_table.sort_values(by='Rank', inplace=True)

    def receive_interest(self, interest_packet, subscriber):
        content_id = ContentIDManager.get_unique_id(interest_packet.name)
        self.content_popularity[interest_packet.name] += 1

        # Log the interest received
        self.log_event(f"Received interest for {interest_packet.name} with ID {content_id} from Subscriber {subscriber.name}")

        access_time = random.uniform(0.01, 0.1)
        self.total_cache_access_time += access_time
        
        # Prevent loops by checking if this router has already been visited
        if self.name in interest_packet.visited:
            self.log_event(f"Loop detected: Dropping interest for {interest_packet.name} at {self.name}")
            return
        
        # No loop only increment total_requests
        self.total_requests += 1
        
        # hop count tracking
        if not hasattr(interest_packet, 'actual_hop_count'):
            interest_packet.actual_hop_count = 0
        interest_packet.actual_hop_count += 1
        
        # Add this router to the packet's path
        interest_packet.path.append(self.name)
        interest_packet.visited.add(self.name)
        
        if interest_packet.name not in self.pit:
            self.pit[interest_packet.name] = subscriber.name
            self.save_pit()

        if interest_packet.name in self.cs:
            # Cache hit
            self.cache_hits += 1
            self.requests_served_from_cache += 1
            data_packet = DataPacket(name=interest_packet.name, content=interest_packet.name)
            self.log_event(f"Cache hit: Serving {interest_packet.name} with ID {content_id} from cache")
            subscriber.receive_data(data_packet)
            return
        else:
            # Cache miss: Fetch content from publisher or next-hop router
            self.publisher_hits += 1
            self.log_event(f"Cache miss: Fetching {interest_packet.name} with ID {content_id} from Publisher or other routers")
            next_hop = self.fib.get(interest_packet.name)

            if next_hop:
                if isinstance(next_hop, Router):
                    next_hop.receive_interest(interest_packet, subscriber)
                elif isinstance(next_hop, Publisher):
                    data_packet = next_hop.serve_content(interest_packet.name)
                    if data_packet:
                        self.receive_data(data_packet)
                        subscriber.receive_data(data_packet)
            else:
                self.log_event(f"No route found in FIB for {interest_packet.name}")

            self.requests_served_from_publisher += 1
    
    def save_popularity_table(self, policy):
        """Save the popularity table to a policy-specific CSV, including feedback."""
        os.makedirs(f'Popularity_Table/{policy}', exist_ok=True)
        self.popularity_table.to_csv(f'Popularity_Table/{policy}/Ptable.csv', index=False)
        print(f"Popularity table saved with feedback for {policy}.")

    def receive_data(self, data_packet):
        current_time = datetime.datetime.now()
        # Remove expired content from the cache
        for content, expiry_time in list(self.cache_ttl.items()):
            if current_time > expiry_time:
                self.cs.remove(content)
                self.cache_ttl.pop(content)
                self.log_event(f"Content {content} expired and removed from cache")

        ttl = current_time + datetime.timedelta(minutes=5)
        self.cache_ttl[data_packet.name] = ttl  # Set TTL for new cache entry

        # Handle cache evictions if the limit is reached
        if len(self.cs) >= Router.CACHE_LIMIT:
            self.cache_evictions += 1
            
            # Implement FACR policy eviction
            if self.caching_policy == 'FACR':
                # Identify top 5 popular content by rank in popularity_table
                top_5_popular = set(self.popularity_table.head(5)['Content Name'])
                non_reserved_cache = [item for item in self.cs if item not in top_5_popular]

                # Check if non-reserved cache space is full
                if len(non_reserved_cache) >= (Router.CACHE_LIMIT - Router.TOP_N_POPULAR):
                    to_remove = non_reserved_cache[0]  # Evict the oldest in non-reserved
                    self.cs.remove(to_remove)
                    self.cache_access_times.pop(to_remove, None)
                    self.cache_frequency.pop(to_remove, None)
            else:
            
                if self.caching_policy == 'LRU':
                    lru_content = min(self.cache_access_times, key=self.cache_access_times.get)
                    self.cs.remove(lru_content)
                    self.cache_access_times.pop(lru_content)
                elif self.caching_policy == 'LFU':
                    lfu_content = min(self.cache_frequency, key=self.cache_frequency.get)
                    self.cs.remove(lfu_content)
                    self.cache_frequency.pop(lfu_content)
                elif self.caching_policy == 'FIFO':
                    self.cs.pop(0)  # Remove the first cached item (FIFO)
                elif self.caching_policy == 'MRU':
                    mru_content = max(self.cache_access_times, key=self.cache_access_times.get)
                    self.cs.remove(mru_content)
                    self.cache_access_times.pop(mru_content)
                """elif self.caching_policy == 'FACR':
                    # Reserve space for the top 5 popular items in the cache
                    top_5_popular = set(self.popularity_table.head(5)['Content Name'])
                    non_reserved_cache = [item for item in self.cs if item not in top_5_popular]

                # Check if non-reserved cache space is full
                if len(non_reserved_cache) >= (Router.CACHE_LIMIT - 5):
                    # Remove the oldest item from non-reserved cache
                    to_remove = non_reserved_cache[0]
                    self.cs.remove(to_remove)
                    self.cache_access_times.pop(to_remove, None)
                    self.cache_frequency.pop(to_remove, None)"""

        # Cache the new content
        if data_packet.name not in self.cs:
            self.cs.append(data_packet.name)
        if self.caching_policy in ['LRU', 'MRU']:
            self.cache_access_times[data_packet.name] = current_time
        elif self.caching_policy == 'LFU':
            self.cache_frequency[data_packet.name] += 1
        self.save_cs()    ##Save and update

        # Update popularity metrics for the content
        self.update_popularity(data_packet.name)
        self.rank_content()
        self.save_popularity_table(self.caching_policy)  # Save the popularity table to Ptable.csv

        # Log caching event
        content_id = ContentIDManager.get_unique_id(data_packet.name)
        self.log_event(f"Cached {data_packet.name} with ID {content_id} in {self.name}'s Content Store with TTL of 5 minutes")
        self.save_cs()


    def save_fib(self):
        fib_dir = os.path.join('Output/FIB', self.name)
        os.makedirs(fib_dir, exist_ok=True)

        with open(f'{fib_dir}/fib.csv', mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Name", "ID", "Next Hop"])
            for name, next_hop in self.fib.items():
                content_id = ContentIDManager.get_unique_id(name)
                next_hop_name = next_hop.name if next_hop else "None"
                writer.writerow([name, content_id, next_hop_name])

    def save_pit(self):
        pit_dir = os.path.join('Output/PIT', self.name)
        os.makedirs(pit_dir, exist_ok=True)

        with open(f'{pit_dir}/pit.csv', mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Name", "ID", "Requester"])
            for name, requester in self.pit.items():
                content_id = ContentIDManager.get_unique_id(name)
                writer.writerow([name, content_id, requester])

    def save_cs(self):
        cs_dir = os.path.join('Output/CS', self.name)
        os.makedirs(cs_dir, exist_ok=True)

        with open(f'{cs_dir}/cs.csv', mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Content", "ID"])
            for content in self.cs:
                content_id = ContentIDManager.get_unique_id(content)
                writer.writerow([content, content_id])

    def log_event(self, message):
        os.makedirs('Logs', exist_ok=True)
        with open(f'Logs/log_{self.name}.txt', 'a') as log_file:
            log_file.write(f"[{datetime.datetime.now()}] {message}\n")


class Publisher(Node):
    def __init__(self, name, folder):
        super().__init__(name)
        self.folder = folder
        self.images = self.load_images()

    def load_images(self):
        images = {}
        os.makedirs(self.folder, exist_ok=True)
        image_files = [f for f in os.listdir(self.folder) if os.path.isfile(os.path.join(self.folder, f))]
        for image_name in image_files:
            file_path = os.path.join(self.folder, image_name)
            images[image_name] = file_path
        return images

    def serve_content(self, content_name):
        if content_name in self.images:
            file_path = self.images[content_name]
            with open(file_path, 'rb') as img_file:
                content = img_file.read()
            return DataPacket(name=content_name, content=content)
        return None

class Subscriber(Node):
    def __init__(self, name):
        super().__init__(name)
        self.active = True

    def send_interest(self, interest_packet, router):
        if isinstance(router, Router):
            router.receive_interest(interest_packet, self)
    
    
    def provide_feedback(self, router, content_name, feedback):
        """Provide feedback on the content after receiving it."""
        print(f"Providing feedback: {feedback} for {content_name} via {router.name}")
        if feedback in ['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike']:
            router.update_popularity(content_name, feedback=feedback)
        else:
            router.update_popularity(content_name, feedback='None')

    def receive_data(self, data_packet):
        print(f"Subscriber {self.name} received data for {data_packet.name}")
        # Assign feedback based on random or behavior-driven logic
        feedback = random.choice(['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike'])
        print(f"Subscriber {self.name} provided feedback: {feedback} for {data_packet.name}")
        self.provide_feedback(self.connected_router, data_packet.name, feedback)


def save_network(routers, publishers, subscribers):
    """Save the network setup to a file."""
    os.makedirs("Saved_Network", exist_ok=True)
    with open("Saved_Network/network_setup.pkl", "wb") as file:
        pickle.dump((routers, publishers, subscribers), file)
    print("Network setup saved successfully.")

def load_network():
    """Load the network setup from a saved file."""
    try:
        with open("Saved_Network/network_setup.pkl", "rb") as file:
            return pickle.load(file)  # Ensure it returns a tuple
    except Exception as e:
        print(f"Failed to load the network: {e}")
        return None

def setup_network():
    """Set up the network or reuse an existing one."""
    if os.path.exists("Saved_Network/network_setup.pkl"):
        choice = input("Use existing network setup? (yes/no): ").strip().lower()
        if choice == 'yes':
            try:
                routers, publishers, subscribers = load_network()  # Proper unpacking
                print("Loaded existing network successfully.")
                return routers, publishers, subscribers
            except Exception as e:
                print(f"Error loading network: {e}. Creating a new network setup...")

    # Helper function to get a valid integer input
    def get_valid_integer(prompt):
        """Prompt user for a positive integer and handle invalid inputs."""
        while True:
            try:
                value = int(input(prompt))
                if value > 0:
                    return value
                else:
                    print("Please enter a positive integer.")
            except ValueError:
                print("Invalid input. Please enter a valid integer.")

    # Get the number of routers with input validation
    num_routers = get_valid_integer("Enter the number of routers: ")
    routers = [Router(f'Router{i}') for i in range(1, num_routers + 1)]  # Initialize routers here

    # Initialize publishers
    publisher1 = Publisher('Publisher1', 'cats')
    publisher2 = Publisher('Publisher2', 'dogs')
    publishers = [publisher1, publisher2]

    # Get the number of subscribers with input validation
    num_subscribers = get_valid_integer("Enter the number of subscribers: ")
    subscribers = [Subscriber(f'Subscriber{i}') for i in range(1, num_subscribers + 1)]

    # Connect subscribers to routers in a round-robin fashion
    for i, subscriber in enumerate(subscribers):
        router_index = i % len(routers)
        subscriber.connected_router = routers[router_index]

    # Initialize the content ID manager with the publishers' data
    ContentIDManager.initialize_index(publishers)

    # Set up the Forwarding Information Base (FIB) with multiple paths
    for i, router in enumerate(routers):
        # Connect to the next router in sequence
        if i < len(routers) - 1:
            router.fib.update({f"cat_image{j}.jpg": routers[i + 1] for j in range(1, 51)})
            router.fib.update({f"dog_image{j}.jpg": routers[i + 1] for j in range(1, 51)})

        # Add additional paths (loops) to other non-adjacent routers
        for j in range(i + 2, min(i + 4, len(routers))):  # Avoid connecting directly adjacent routers
            router.fib.update({f"cat_image{k}.jpg": routers[j] for k in range(1, 51)})
            router.fib.update({f"dog_image{k}.jpg": routers[j] for k in range(1, 51)})

    # The last router connects directly to publishers
    routers[-1].fib.update({f"cat_image{j}.jpg": publisher1 for j in range(1, 51)})
    routers[-1].fib.update({f"dog_image{j}.jpg": publisher2 for j in range(1, 51)})

    # Save the new network setup to a file
    save_network(routers, publishers, subscribers)

    print("New network setup created and saved.")
    return routers, publishers, subscribers  # Return the new network components

def estimate_max_possible_hops(routers, starting_router):
    """Estimate the maximum possible hops from starting router to publisher."""
    return len(routers)  # Simple assumption for now, improves real behavior

def run_simulation(routers, publishers, subscribers, policy, iterations):
    # Reset routers to ensure a clean state
    for router in routers:
        router.caching_policy = policy
        router.reset()

    contents = [f"cat_image{i}.jpg" for i in range(1, 51)] + [f"dog_image{i}.jpg" for i in range(1, 51)]
    simulation_data = []
    active_prob = 0.9  # Subscriber active probability

    # Dictionary to collect feature data for training ML model later
    feature_data = {policy: [] for policy in ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']}

    # Run the simulation for the given policy
    for iteration in range(1, iterations + 1):
        for router in routers:
            router.caching_policy = policy  # Set the current policy for each router
            router.reset()  # Reset router stats for the new iteration

        # Simulate the network behavior for active subscribers and requests
        for subscriber in subscribers:
            subscriber.active = random.random() < active_prob

        active_subscribers = [s for s in subscribers if s.active]
        if active_subscribers:
            subscriber = random.choice(active_subscribers)
            content_to_request = random.choice(contents)

            interest_packet = InterestPacket(name=content_to_request)
            interest_packet.original_hop_count = estimate_max_possible_hops(routers, subscriber.connected_router)

            print(f"Subscriber {subscriber.name} requesting {content_to_request}")
            subscriber.send_interest(interest_packet, subscriber.connected_router)

            interest_packet.actual_hop_count = len(interest_packet.path)
            subscriber.last_interest_packet = interest_packet

            print(f"Path taken for {content_to_request}: {interest_packet.path}")

        # Calculate metrics
        latency = random.uniform(0.01, 0.1)
        total_requests = sum(router.cache_hits + router.publisher_hits for router in routers)
        total_cache_hits = sum(router.cache_hits for router in routers)
        avg_cache_hit = (total_cache_hits / total_requests) * 100 if total_requests > 0 else 0
        avg_latency = latency / total_requests if total_requests > 0 else 0

        hop_reduction_ratios = []
        for subscriber in subscribers:
            if hasattr(subscriber, 'last_interest_packet'):
                pkt = subscriber.last_interest_packet
                if pkt.original_hop_count > 0:
                    reduction = (pkt.original_hop_count - pkt.actual_hop_count) / pkt.original_hop_count
                    hop_reduction_ratios.append(reduction)

        total_hop_reduction = sum(hop_reduction_ratios) / len(hop_reduction_ratios) if hop_reduction_ratios else 0

        # Save one row of simulation data for the current iteration
        simulation_data.append([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            len(active_subscribers),
            total_requests,
            total_hop_reduction,
            avg_cache_hit,
            avg_latency
        ])

        # Collect features for this iteration for each policy
        current_features = {
            'Iteration': iteration,
            'Cache Hit Ratio': avg_cache_hit,
            'Latency': avg_latency,
            'Hop Reduction': total_hop_reduction,
            'No of Clients': len(active_subscribers),
            'Total Requests': total_requests,
            'Feedback Score': calculate_feedback_score(subscribers),  # Assuming you have a method to calculate feedback
            'Previous Policy': policy  # The policy used in the current iteration
        }

        # Add the collected features for this iteration to the corresponding policy
        features_row = [
            iteration, current_features['Cache Hit Ratio'], current_features['Latency'],
            current_features['Hop Reduction'], current_features['No of Clients'],
            current_features['Total Requests'], current_features['Feedback Score'], current_features['Previous Policy']
        ]
        
        # Append features for this iteration and policy to the feature data
        feature_data[policy].append(features_row)

    # Save the collected features to CSV after the simulation for each policy
    for policy_key in feature_data:
        save_features_to_csv(feature_data[policy_key], policy_key)

    # Save the simulation statistics for the given policy (this was the original functionality)
    save_policy_stats(policy, simulation_data)
    plot_simulation_log(simulation_data, policy)

    return {
        "Policy": policy,
        "Simulation Data": simulation_data,
        "Total Requests": total_requests,
        "Cache Hits": total_cache_hits,
        "Publisher Hits": sum(router.publisher_hits for router in routers),
        "Cache Hit Ratio": avg_cache_hit
    }


def save_features_to_csv(features, policy):
    """Save features for the given policy to a CSV file"""
    # Create folder if not exists
    os.makedirs(f'ML_Training_Data/{policy}', exist_ok=True)
    
    # Create a DataFrame to hold the feature data
    feature_df = pd.DataFrame(features, columns=['Iteration', 'Cache Hit Ratio', 'Latency', 'Hop Reduction', 'No of Clients', 'Total Requests', 'Feedback Score', 'Previous Policy'])
    
    # Save to CSV file for the current policy
    feature_df.to_csv(f'ML_Training_Data/{policy}/features.csv', mode='a', header=not os.path.exists(f'ML_Training_Data/{policy}/features.csv'), index=False)
    print(f"Features saved for {policy}.")

def calculate_feedback_score(subscribers):
    """Calculate feedback score based on subscriber feedback"""
    total_feedback_score = 0
    for subscriber in subscribers:
        feedback = random.choice(['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike'])
        if feedback == 'like':
            total_feedback_score += 1
        elif feedback == 'dislike':
            total_feedback_score -= 1
        elif feedback == 'neutral':
            total_feedback_score += 0
        elif feedback == 'highly_like':
            total_feedback_score += 2
        elif feedback == 'highly_dislike':
            total_feedback_score -= 2
    return total_feedback_score


def run_simulation_with_ml_policy(routers, publishers, subscribers, iterations):
    ml_policy = MLPolicy()  # Initialize the ML model to predict the best policy
    feature_data = []  # This will hold all feature data for training the ML model

    for iteration in range(1, iterations + 1):
        # 1. Extract the current network features
        current_features = {
            'Iteration': iteration,
            'Cache Hit Ratio': calculate_cache_hit_ratio(routers),
            'Latency': calculate_latency(routers),
            'Hop Reduction': calculate_hop_reduction(routers),
            'No of Clients': len([s for s in subscribers if s.active]),
            'Total Requests': calculate_total_requests(routers),
            'Top Content Popularity': calculate_top_content_popularity(routers),
            'Feedback Score': calculate_feedback_score(subscribers),
            'Previous Policy': 'None'  # Initially, it's 'None', to be updated later
        }

        # 2. Save the feature data for training later
        features_row = [
            iteration, current_features['Cache Hit Ratio'], current_features['Latency'], current_features['Hop Reduction'],
            current_features['No of Clients'], current_features['Total Requests'], current_features['Top Content Popularity'],
            current_features['Feedback Score'], current_features['Previous Policy']
        ]
        feature_data.append(features_row)

        # 3. Save features to CSV after every iteration (or periodically)
        save_features_to_csv(feature_data)

    return feature_data


def save_features_to_csv(features, policy):
    """Save features for the given policy to a CSV file"""
    # Create folder if not exists
    os.makedirs(f'ML_Training_Data/{policy}', exist_ok=True)
    
    # Create a DataFrame to hold the feature data
    feature_df = pd.DataFrame(features, columns=[
        'Iteration', 'Cache Hit Ratio', 'Latency', 'Hop Reduction',
        'No of Clients', 'Total Requests', 'Top Content Popularity',
        'Feedback Score', 'Previous Policy'
    ])

    # Save to CSV file for the current policy
    feature_df.to_csv(f'ML_Training_Data/{policy}/features.csv', mode='a', header=not os.path.exists(f'ML_Training_Data/{policy}/features.csv'), index=False)
    print(f"Features saved for {policy}.")

def train_model():
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']  # List of policies
    all_data = []

    for policy in policies:
        # Read the features from the saved CSV for the current policy
        data = pd.read_csv(f'ML_Training_Data/{policy}/features.csv')
        
        # Add the policy column (label) to the dataset
        data['Policy'] = policy
        all_data.append(data)
    
    # Combine all data from different policies into a single dataframe
    full_data = pd.concat(all_data, ignore_index=True)
    
    # Separate features (X) and target labels (y)
    X = full_data.drop(columns=['Policy', 'Iteration'])  # Drop the 'Policy' and 'Iteration' columns from the features
    y = full_data['Policy']  # The target is the 'Policy' column
    
    # Initialize and train the RandomForestClassifier
    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X, y)

    # Save the trained model to a file
    with open('ml_models/random_forest_policy_selector.pkl', 'wb') as f:
        pickle.dump(clf, f)
    
    print("Model trained and saved successfully!")

class MLPolicy:
    def __init__(self, model_path='ml_models/random_forest_policy_selector.pkl'):
        with open(model_path, 'rb') as f:
            self.model = pickle.load(f)

    def predict_best_policy(self, features):
        # Convert features into a DataFrame (this is what the model expects)
        df = pd.DataFrame([features])
        # Predict the best policy based on current features
        label = self.model.predict(df)[0]
        return ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR'][label]  # Map back to policy name

def generate_global_ptable():
    # Dictionary to store cumulative popularity across policies
    global_popularity = {}

    # List of policies used in the simulation
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']

    # Loop through each policy's Ptable to collect and aggregate popularity data
    for policy in policies:
        ptable_path = f'Popularity_Table/{policy}/Ptable.csv'
        if os.path.exists(ptable_path):
            policy_ptable = pd.read_csv(ptable_path)
            
            # Accumulate popularity for each content across policies
            for _, row in policy_ptable.iterrows():
                content_name = row['Content Name']
                popularity = row['Popularity']
                
                # Add popularity to global score, initializing if new
                if content_name in global_popularity:
                    global_popularity[content_name] += popularity
                else:
                    global_popularity[content_name] = popularity

    # Create a DataFrame from the aggregated popularity dictionary
    global_ptable = pd.DataFrame(list(global_popularity.items()), columns=['Content Name', 'Aggregated Popularity'])

    # Sort and rank by the aggregated popularity
    global_ptable.sort_values(by='Aggregated Popularity', ascending=False, inplace=True)
    global_ptable['Rank'] = range(1, len(global_ptable) + 1)  # Sequential ranking

    # Save Global Ptable as a CSV file
    os.makedirs('Popularity_Table/Global', exist_ok=True)
    global_ptable.to_csv('Popularity_Table/Global/Global_Ptable.csv', index=False)

    print("Global Ptable generated and saved.")

#Helper functions 
def save_simulation_log(simulation_data):
    os.makedirs('Simulation_Log', exist_ok=True)
    with open('Simulation_Log/simulation_log.csv', mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Simulation Time", "No of Clients", "Total no of requests", "Average hop reduction", "Average Cache hit", "Average latency"])
        writer.writerows(simulation_data)
    print("Simulation log saved successfully.")

def save_policy_stats(policy, simulation_data):
    os.makedirs('Policy_Stats', exist_ok=True)
    filename = f'Policy_Stats/{policy}_stats.csv'
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Simulation Time", "No of Clients", "Total Requests", "Hop Reduction", "Cache Hit Ratio", "Latency"])
        writer.writerows(simulation_data)
    print(f"Stats saved for {policy} policy.")

def save_results(policy_stats):
    """Save the combined results of all policy simulations to a CSV file."""
    os.makedirs('Simulation_Results', exist_ok=True)
    filename = 'Simulation_Results/policy_comparison.csv'
    
    # Save all policy statistics into a CSV file
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        # Write header row
        writer.writerow(["Policy", "Iteration", "Cache Hit Ratio", "Latency", "Hop Reduction"])

        # Write each row of stats for every policy and iteration
        for stat in policy_stats:
            writer.writerow([
                stat["Policy"],
                stat["Iteration"],
                stat["Cache Hit Ratio"],
                stat["Latency"],
                stat["Hop Reduction"]
            ])

    print(f"Results saved to {filename}.")

def plot_policy_comparison(policy_stats):
    df = pd.DataFrame(policy_stats)

    # Calculate mean Cache Hit Ratio per policy
    cache_hit_avg = df.groupby('Policy')['Cache Hit Ratio'].mean()

    # Plot
    plt.figure(figsize=(8, 5))
    cache_hit_avg.plot(kind='bar', color='blue', edgecolor='black')

    plt.title('Average Cache Hit Ratio per Caching Policy', fontsize=14, fontweight='bold')
    plt.xlabel('Policy', fontsize=12)
    plt.ylabel('Cache Hit Ratio (%)', fontsize=12)
    plt.xticks(rotation=45, fontsize=10)
    plt.yticks(fontsize=10)
    plt.grid(axis='y', linestyle='--', linewidth=0.5)

    plt.tight_layout()
    plt.show()

def plot_network_graph(routers, publishers, subscribers):
    if not isinstance(routers, list):
        raise TypeError(f"Expected routers to be a list, but got {type(routers)}")

    G = nx.Graph()

    # Add routers
    for router in routers:
        G.add_node(router.name, label='Router', color='lightblue')

    # Add publishers
    for publisher in publishers:
        G.add_node(publisher.name, label='Publisher', color='lightgreen')

    # Add subscribers
    for subscriber in subscribers:
        G.add_node(subscriber.name, label='Subscriber', color='salmon')

    # Add edges (Router-Router, Router-Publisher, Subscriber-Router)
    for router in routers:
        for destination, next_hop in router.fib.items():
            if next_hop and next_hop.name in G:
                G.add_edge(router.name, next_hop.name)

    for subscriber in subscribers:
        if subscriber.connected_router:
            G.add_edge(subscriber.name, subscriber.connected_router.name)

    for router in routers:
        for destination, next_hop in router.fib.items():
            if isinstance(next_hop, Publisher) and next_hop.name in G:
                G.add_edge(router.name, next_hop.name)

    # Prepare for drawing
    colors = [G.nodes[node]['color'] for node in G.nodes]
    pos = nx.spring_layout(G, seed=42)  # Fixed seed for reproducibility

    plt.figure(figsize=(12, 9))
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=800, alpha=0.9)
    nx.draw_networkx_edges(G, pos, width=1.2, alpha=0.7)
    nx.draw_networkx_labels(G, pos, font_size=9, font_family="sans-serif", font_weight="bold")

    plt.title("Network Topology: Routers, Publishers, and Subscribers", fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()
    plt.show()

def plot_simulation_log(simulation_data, policy):
    df = pd.DataFrame(simulation_data, columns=[
        "Simulation Time", "No of Clients", "Total Requests", 
        "Hop Reduction", "Cache Hit Ratio", "Latency"
    ])
    
    df['Iteration'] = range(1, len(df) + 1)

    fig, axs = plt.subplots(2, 2, figsize=(14, 10))

    # Define plotting properties
    plot_settings = {
        "linewidth": 1.8,
        "marker": "o",
        "markersize": 4,
        "markevery": 10,
    }

    axs[0, 0].plot(df["Iteration"], df["No of Clients"], color='blue', **plot_settings)
    axs[0, 0].set_title('No of Clients over Iterations', fontsize=12, fontweight='bold')
    axs[0, 0].set_xlabel('Iteration', fontsize=10)
    axs[0, 0].set_ylabel('No of Clients', fontsize=10)
    axs[0, 0].grid(True, linestyle='--', linewidth=0.5)

    axs[0, 1].plot(df["Iteration"], df["Cache Hit Ratio"], color='darkgreen', **plot_settings)
    axs[0, 1].set_title('Cache Hit Ratio over Iterations', fontsize=12, fontweight='bold')
    axs[0, 1].set_xlabel('Iteration', fontsize=10)
    axs[0, 1].set_ylabel('Cache Hit Ratio (%)', fontsize=10)
    axs[0, 1].grid(True, linestyle='--', linewidth=0.5)

    axs[1, 0].plot(df["Iteration"], df["Latency"], color='red', **plot_settings)
    axs[1, 0].set_title('Latency over Iterations', fontsize=12, fontweight='bold')
    axs[1, 0].set_xlabel('Iteration', fontsize=10)
    axs[1, 0].set_ylabel('Latency', fontsize=10)
    axs[1, 0].grid(True, linestyle='--', linewidth=0.5)

    axs[1, 1].plot(df["Iteration"], df["Hop Reduction"], color='purple', **plot_settings)
    axs[1, 1].set_title('Hop Reduction over Iterations', fontsize=12, fontweight='bold')
    axs[1, 1].set_xlabel('Iteration', fontsize=10)
    axs[1, 1].set_ylabel('Hop Reduction', fontsize=10)
    axs[1, 1].grid(True, linestyle='--', linewidth=0.5)

    plt.suptitle(f"Simulation Results for {policy} Policy", fontsize=14, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.show()

def plot_merged_graph(policy_stats):
    """Plot a merged graph comparing all traditional caching policies."""
    df = pd.DataFrame(policy_stats)

    fig, axs = plt.subplots(1, 3, figsize=(18, 6))

    # Define consistent colors for traditional policies
    traditional_colors = {
        'LRU': 'navy',
        'LFU': 'darkgreen',
        'FIFO': 'darkorange',
        'MRU': 'indigo',
        'FACR': 'saddlebrown'
    }

    # Common settings
    plot_settings = {
        "linewidth": 1.8,
        "marker": "o",
        "markersize": 4,
        "markevery": 10,  # ✅ Markers every 10 points (as you want)
    }

    metrics = ["Cache Hit Ratio", "Latency", "Hop Reduction"]

    for i, metric in enumerate(metrics):
        ax = axs[i]
        for policy in df["Policy"].unique():
            policy_data = df[df["Policy"] == policy]
            ax.plot(
                policy_data["Iteration"], policy_data[metric],
                label=policy,
                color=traditional_colors.get(policy, 'gray'),
                linestyle='-',
                **plot_settings
            )

        ax.set_xlabel("Iteration", fontsize=10)
        ax.set_ylabel(metric, fontsize=10)
        ax.set_title(f"{metric} Comparison", fontsize=12, fontweight='bold')
        ax.grid(True, linestyle='--', linewidth=0.5)
        ax.legend(
            loc='best',
            fontsize='x-small',
            frameon=False,
            handlelength=2,
            labelspacing=0.3,
            borderpad=0.3,
            handletextpad=0.4
        )

    plt.suptitle("Comparison of Caching Policies: LRU, LFU, FIFO, MRU, FACR", fontsize=14, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.show()

def main():
    # Load existing network or create a new one
    routers, publishers, subscribers = setup_network()

    # Plot the network topology at the beginning
    plot_network_graph(routers, publishers, subscribers)

    # Get the number of iterations for the simulation
    iterations = int(input("Enter the number of content requests in the simulation: "))

    # Feature data will hold all the feature data collected during the simulation
    feature_data = []

    # Run the simulation with the ML policy dynamically switching between policies
    feature_data = run_simulation_with_ml_policy(routers, publishers, subscribers, iterations)

    # Save all feature data to CSV after the simulation
    save_features_to_csv(feature_data, 'ML_Training_Data')  # This will save features across iterations for training the model.

    # Optionally, plot the simulation log
    # plot_simulation_log(feature_data, 'MLPolicy')  # You may want to plot results if needed.

    # Print a message to indicate the completion of the simulation and feature saving
    print("Simulation with dynamic ML policy switching completed successfully!")

    # Train the model using the data collected during the simulation
    train_model()  # This will read the saved features and train the model.

    # Optional: You can save your final results and generate the Global Popularity Table (after all policies have been simulated)
    generate_global_ptable()

if __name__ == "__main__":
    main()
