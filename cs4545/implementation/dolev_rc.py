import asyncio
import random
import time
from typing import Dict

       
from ipv8.community import CommunitySettings
from ipv8.messaging.payload_dataclass import dataclass
from ipv8.types import Peer

from cs4545.system.da_types import DistributedAlgorithm, message_wrapper
from typing import List
from ..system.da_types import ConnectionMessage


class DolevConfig:
    def __init__(self, starter_nodes=[1, 0, 2, 4], f = 2, malicious_nodes=[7, 8]):
        self.starter_nodes = starter_nodes
        self.f = f
        self.malicious_nodes = malicious_nodes

@dataclass(
    msg_id=3 # TODO: should this be different for different messages?
)  # The value 1 identifies this message and must be unique per community.
class DolevMessage:
    message: str
    message_id: int
    path: List[int]

class DolevMetrics:
    node_count: int = 0
    byzantine_count: int = 0
    connectivity: int = 0
    message_count: int = 0
    last_message_count: int = 0
    start_time: Dict[int, float] = {}
    end_time: Dict[int, float] = {}
    latency: float = 0.0

class BasicDolevRC(DistributedAlgorithm):
    def __init__(self, settings: CommunitySettings, parameters: DolevConfig=DolevConfig()) -> None:
        super().__init__(settings)
        
        if parameters.f != len(parameters.malicious_nodes):
            print("Error: f should be equal to the length of malicious_nodes! Aborting......")
            self.stop()
        
        self.f = parameters.f
        self.starter_nodes = parameters.starter_nodes
        self.malicious_nodes = parameters.malicious_nodes

        #assume no malicious node exist rn
        self.is_malicious: bool = False#(self.node_id in self.malicious_nodes) 
        self.malicious_behaviour = None

        for mal_node in self.malicious_nodes:
            if(mal_node in  self.starter_nodes):
                self.malicious_behaviour = "generate_fake_msg"
            else : 
                self.malicious_behaviour = "modify_msg_id"

        self.is_delivered: dict[int, bool] = {}
        self.message_paths: dict[int, set[tuple]] = {}
        self.message_broadcast_cnt = 0

        #optimization control vairable
        self.MD1 = False
        self.MD2 = False
        self.MD3 = False
        self.MD4 = False
        self.MD5 = False

        self.add_message_handler(DolevMessage, self.on_message)
        
        self.metrics = DolevMetrics()

    def generate_message_id(self, msg: str) -> int:
        self.message_broadcast_cnt += 1
        return self.node_id * 37 + self.message_broadcast_cnt + hash(msg)
    
    def generate_message(self) -> DolevMessage:
        msg =  ''.join([random.choice(['Y', 'M', 'C', 'A']) for _ in range(4)])
        id = self.generate_message_id(msg)
        return DolevMessage(msg, id, [])
    
    def generate_malicious_msg(self) -> DolevMessage:

        msg = f"fake news!"
        id = self.generate_message_id(msg)

        fake_msg_log = f"[Malicious Node {self.node_id}] generated malicious msg to send"
        self.append_output(fake_msg_log)
        print(fake_msg_log)
        
        return DolevMessage(msg,id,[])
    
    def mal_modify_msg(self, payload) ->  DolevMessage:

        if payload:
            original_msg = payload.msg
            payload.msg = f"fake behaviour set on: {original_msg}"
            payload.id = self.generate_message_id(payload.msg)
        
            fake_msg_log = f"[Malicious Node {self.node_id}] tampered the original msg"
            self.append_output(fake_msg_log)
            print(fake_msg_log)

            return payload

    def execute_mal_process(self, msg) -> DolevMessage:

        (behaviour,args) = {
            "generate_fake_msg" : (self.generate_malicious_msg, ()),
            "modify_msg_id" : (self.mal_modify_msg, (msg,)),
        }.get(self.malicious_behaviour, (None,None))

        try:
            if behaviour is None:
                raise ValueError("No valid behavior was selected for malicious processing.")
        
            processed_mal_msg = behaviour(*args)

        except Exception as e:
            print(f"Error in execute_mal_process: {e}")
            raise
        
        return processed_mal_msg
    


    async def on_start(self):
        if self.node_id in self.starter_nodes:
            await self.on_start_as_starter()
        print(f"[DEBUG] Node {self.node_id} starting with starter_nodes={self.starter_nodes}")

        # print(f"[Node {self.node_id}] Starting algorithm with peers {[x.address for x in self.get_peers()]} and {self.nodes}")
        if self.node_id == self.starting_node:
            # Checking if all node states are ready
            all_ready = all([x == "ready" for x in self.node_states.values()])
            while not all_ready:
                print(f"[DEBUG] Node {self.node_id} waiting, states={self.node_states}")
                await asyncio.sleep(1)
                all_ready = all([x == "ready" for x in self.node_states.values()])
                
            print(f"[DEBUG] Node {self.node_id} has received all ready states, ready to run")
            await asyncio.sleep(1)

        print(f"[DEBUG] Node {self.node_id} peers: {[x.address for x in self.get_peers()]}")
        print(f"[Node {self.node_id}] is ready")
        for peer in self.get_peers():
            self.ez_send(peer, ConnectionMessage(self.node_id, "ready"))
            

    async def on_start_as_starter(self):
        # By default we broadcast a message as starter, but everyone should be able to trigger a broadcast as well.
        print(f"[DEBUG] Node {self.node_id} entering on_start_as_starter")
        message = self.generate_message()
        print(f"[DEBUG] Generated message: {message}")
        await self.on_broadcast(message)


    async def on_broadcast(self, message: DolevMessage) -> None:
        # Assuming everything has been set up well for this node (delivered, paths, ...)
        print(f"[DEBUG] Node {self.node_id} entering on_broadcast")
        print(f"[DEBUG] Peers count: {len(self.get_peers())}")

        print(f"Node {self.node_id} is starting Dolev's protocol")
        
        peers = self.get_peers()

        #if the node is a malicious node, then generate a fake msg to deliver to maximum f 
        if self.is_malicious :
            max_broadcast_cnt = self.f
            message = self.execute_mal_process(message)

        else:
            max_broadcast_cnt = len(peers)

        try:
            for peer in peers[:max_broadcast_cnt]:

                peer_id = self.node_id_from_peer(peer)

                broad_cast_log = f"[Node {self.node_id}] Sent message to node {peer_id}"
                self.append_output(broad_cast_log)
                print(broad_cast_log)

                self.ez_send(peer, message)

        except Exception as e:
            print(f"Error in on_broadcast: {e}")
            raise e
        
        await self.trigger_delivery(message)

    @message_wrapper(DolevMessage)
    async def on_message(self, peer: Peer, payload: DolevMessage) -> None:

        sender_id = self.node_id_from_peer(peer)
        
        # if the node is malicious, it will modify the msg
        if self.is_malicious and (self.node_id not in self.starter_nodes):
            payload = self.execute_mal_process(payload)

        try:

            recieved_log = f"[Node {self.node_id}] Got message from node: {sender_id} with path {payload.path}"
            self.append_output(recieved_log)
            print(recieved_log)

            new_path = payload.path + [sender_id]

            #self.paths.add(tuple(new_path))
            if self.metrics.start_time.get(payload.message_id, 0) == 0:
                self.metrics_init()
                self.set_start_time(payload.message_id)
            
            self.message_paths.setdefault(payload.message_id, set()).add(tuple(new_path))

            for neighbor in self.get_peers():
                neighbor_id = self.node_id_from_peer(neighbor)
                if neighbor_id != self.node_id and neighbor_id not in new_path:

                    msg_log = f"[Node {self.node_id}] Sent message to node {neighbor_id} with path {new_path} : {payload.message_id}"
                    self.append_output(msg_log)

                    print(msg_log)

                    self.ez_send(neighbor, DolevMessage(payload.message, payload.message_id, new_path))

            #if len(self.message_paths.get(payload.message_id)) >= (self.f + 1): history line remaining, will be removed
            
            #if the node is not malicious and not delivered and there is f+1 disjoint_path_
            if not self.is_malicious and not self.is_delivered.get(payload.message_id) and self.find_disjoint_paths_ok(payload.message_id):
                # print(f"Node {self.node_id} has enough node-disjoint paths, delivering message: {payload.message}")
                self.metrics.message_count = len(self._message_history)
                
                disjoint_path_find_log = f"Enough node-disjoint paths found, message will be delivered"
                self.append_output(disjoint_path_find_log)
                print(disjoint_path_find_log)

                await self.trigger_delivery(payload)
           
        except Exception as e:
            print(f"Error in on_message: {e}")
            raise e

    async def trigger_delivery(self, message: DolevMessage):

        deliver_log = f"Node {self.node_id} delivering message: {message.message}"
        self.append_output(deliver_log)
        print(deliver_log)

        for msg_id, status in self.is_delivered.items():
            self.append_output(f"Delivered Messages: Message ID: {msg_id}, Delivered: {status}")

        self.save_algorithm_output()
        self.save_node_stats()

        self.is_delivered[message.message_id] = True
        
        self.get_end_time_and_latency(message.message_id)
        self.write_metrics()

    
    def find_disjoint_paths_ok(self, msg_id) -> bool:
        if not self.message_paths.get(msg_id):
            return False
        disjoint_paths = []
        used_nodes = set()
        paths_sorted = sorted(self.message_paths.get(msg_id), key=len)
        
        for path in paths_sorted:
            path = path[1:]
            if not set(path).intersection(used_nodes):
                disjoint_paths.append(list(path))
                used_nodes.update(path)

                if len(disjoint_paths) >= (self.f + 1):

                    path_log = f"[Node {self.node_id}] Terminate, disjoint paths: {disjoint_paths}" 
                    self.append_output(path_log)
                    print(path_log)
                    return True
        return False

    def set_start_time(self, msg_id):
        self.metrics.start_time[msg_id] = time.time()
        
    def get_end_time_and_latency(self, msg_id):
        self.metrics.end_time[msg_id] = time.time()
        start_time = self.metrics.start_time.get(msg_id, 0.0)

        self.metrics.latency = self.metrics.end_time.get(msg_id) - start_time
        
    def write_metrics(self):
        metrics_log = f"{self.node_id},{self.metrics.node_count},{self.metrics.byzantine_count},{self.metrics.connectivity},{self.metrics.latency:.3f},{self.metrics.message_count - self.metrics.last_message_count}"
        self.metrics.last_message_count = self.metrics.message_count
        with open("output/metrics_output.csv", "a") as f:
            f.write(metrics_log + "\n")
        
    def metrics_init(self):
        self.metrics.node_count = len(self.nodes)
        self.metrics.byzantine_count = len(self.malicious_nodes)
        self.metrics.connectivity = len(self.get_peers())
        self.metrics.message_count = 0