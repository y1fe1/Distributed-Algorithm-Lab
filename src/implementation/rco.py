import random
import datetime
import asyncio
import time

from ipv8.community import CommunitySettings

from src.implementation.dolev_rc_new import DolevMessage, MessageType
from src.implementation.node_log import LOG_LEVEL
from src.implementation.bracha_rb import BrachaRB, BrachaConfig

class RCOConfig(BrachaConfig):
    def __init__(self, broadcasters={0:1, 1:1}, malicious_nodes=[], N=10, msg_level=LOG_LEVEL.WARNING, causal_broadcast = {0: [8,8,9,6,4], 1: [2,3,5]}):
        """
        Previously, we use broadcasters = {1:2, 2:1, ...} to launch concurrent broadcasts.
        From now on, the messages should be made causally related.
        The way we do this is to have the message specify its successor(s), i.e. the next node to broadcast.
        eg. If a message is "#msg_content#4698" sent by 1, then broadcasts will go as 1->8->9->6->4->end 
        """
        super().__init__(broadcasters, malicious_nodes, N, msg_level)
        self.causal_broadcast = causal_broadcast

class RCO(BrachaRB):
    def __init__(self, settings: CommunitySettings, parameters=RCOConfig()):
        super().__init__(settings, parameters)
        self.causal_broadcast = parameters.causal_broadcast
        self.vector_clock = [0 for _ in range(self.N)]
        self.pending: set[tuple[int, DolevMessage]] = set()

    def gen_output_file_path(self, test_name: str = "RCO_TEST"):
        return super().gen_output_file_path(test_name)
    
    async def on_start(self):
        await super().on_start()

    async def on_start_as_starter(self):
        await super().on_start_as_starter()

    def compare_vector_lock(self, new_VC) -> bool:
        vec_compare_result = all(v >= nv for v, nv in zip(self.vector_clock, new_VC))
        self.msg_log.log(self.msg_level, f"Comparing Vectors: {self.vector_clock} >= {new_VC}, {vec_compare_result}")
        return vec_compare_result

    def generate_message(self, old_queue = None) -> DolevMessage:
        msg = f"msg_{self.message_broadcast_cnt+1}th_" + \
        "".join([random.choice(['TUD', 'NUQ', 'LOO', 'THU']) for _ in range(6)])

        if old_queue is None:
            queue = self.causal_broadcast[self.node_id]
        else:
            #old_queue.pop(0)
            queue = old_queue.copy()

        u_id = self.get_uid_pred()
        msg_id = self.generate_message_id(msg)
        author_id = self.node_id
        return DolevMessage(u_id, msg, msg_id, self.node_id, [],
                            self.vector_clock, queue, MessageType.BRACHA.value, True, author_id)

    async def on_broadcast(self, message: DolevMessage):
        """ upon event < RCO, Broadcast | M > do """

        self.msg_log.log(self.msg_level, f"Node {self.node_id} is RCO broadcasting: {message.message}")

        self.trigger_RCO_delivery(message)
        await super().on_broadcast(message)
        self.vector_clock[self.node_id] += 1

    def trigger_Bracha_Delivery(self, payload):
        """ upon event < RB, Deliver | M > do """

        time.sleep(random.choice([0, 2]))
        # apply random delay

        super().trigger_Bracha_Delivery(payload)
        author = payload.author_id

        self.msg_log.log(self.msg_level, f"Node {self.node_id} BRB Delivered: {payload.message} from {author}")

        if author != self.node_id: 
            self.pending.add((author, payload))

            self.msg_log.log(self.msg_level, f"My pending: {self.pending}")

            self.deliver_pending()

    def deliver_pending(self):
        """ procedure deliver pending """

        self.msg_log.log(self.msg_level, f"Node {self.node_id} is entering deliver_pending")

        while True:
            to_keep = set()
            flag = False
            for author, msg in self.pending:
                if self.compare_vector_lock(msg.vector_clock):
                    self.trigger_RCO_delivery(msg)
                    self.vector_clock[author] += 1

                    self.msg_log.log(self.msg_level, f"VC[{author}] increased by 1. Current: {self.vector_clock}")

                    flag = True
                else:
                    to_keep.add((author, msg))
            self.pending = to_keep
            if not flag:
                break
        
    def trigger_RCO_delivery(self, payload: DolevMessage):
        """ upon event < RCO, Deliver | M > do """

        delivered_time = datetime.datetime.now()
        author = payload.author_id
        self.msg_log.log(self.msg_level, f"Node {self.node_id} RCO Delivered a message:<{payload.message}>. Time: {delivered_time}. Author: {author}.")

        queue = payload.causal_order_queue
        self.msg_log.log(self.msg_level,f"{queue}, {type(queue)}")

        # if queue:
        #     queue_top = queue[0]
        #     if queue_top == self.node_id:
        #         new_payload = self.generate_message(queue)
        #         self.msg_log.log(self.msg_level, f"Node {self.node_id} is the next broadcaster for message: <{new_payload.message}>. Current message: <{payload.message}>")
        #         asyncio.create_task(self.on_broadcast(new_payload))

        event_broadcast_cnt = 0

        while queue and queue[0] == self.node_id:
            queue.pop(0)
            event_broadcast_cnt +=1
        
        #self.msg_log.log(self.msg_level,f"{queue}, {type(queue)}")

        for i in range(event_broadcast_cnt):

            if i != event_broadcast_cnt - 1:
                new_payload = self.generate_message([]) #this will generate a message that does not continue the causal order queue
            else:
                new_payload = self.generate_message(queue)
                self.msg_log.log(self.msg_level, f"Node {self.node_id} is the next broadcaster for message: <{new_payload}>.")
            asyncio.create_task(self.on_broadcast(new_payload))