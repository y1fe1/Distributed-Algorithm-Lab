import datetime
import logging
import random
import math

from typing import Dict,List
from enum import Enum

from ipv8.community import CommunitySettings
from ipv8.messaging.payload_dataclass import dataclass
from ipv8.types import Peer
from hashlib import sha256

from cs4545.system.da_types import DistributedAlgorithm, message_wrapper
from cs4545.implementation.dolev_rc_new import BasicDolevRC, MessageConfig, DolevMessage
from cs4545.implementation.node_log import message_logger, OutputMetrics, LOG_LEVEL

from cs4545.implementation.dolev_rc_new import MessageType

class BrachaConfig(MessageConfig):
    def __init__(self, broadcasters={1: 2, 2: 1}, malicious_nodes=[], N=10, msg_level=logging.DEBUG):
        assert(len(malicious_nodes) < N / 3)
        super().__init__(broadcasters, malicious_nodes, N, msg_level)
        self.Optim1 = False
        self.Optim2 = False
        self.Optim3 = False

#region Message Definition
# class MessageType(Enum):
#     SEND = 1
#     ECHO = 2
#     READY = 3

# # @dataclass(msg_id=4)
# class SendMessage(DolevMessage):
#     msg_type = MessageType.SEND


# # @dataclass(msg_id=5)
# class EchoMessage(DolevMessage):
#     msg_type = MessageType.ECHO


# # @dataclass(msg_id=6)
# class ReadyMessage(DolevMessage):
#     msg_type = MessageType.READY



# endregion

class BrachaRB(BasicDolevRC):
    def __init__(self, settings: CommunitySettings, parameters=BrachaConfig()) -> None:

        super().__init__(settings, parameters)

        # f should be < N/3

        self.echo_count: dict[str, set[int]] = {}  # message_id -> set of source id that entered echo states
        self.is_echo_sent: dict[str, bool] = {} # message_id -> if the node reach echo state

        self.ready_count: dict[str, set[int]] = {}  # message_id -> ready count
        self.is_ready_sent: dict[str, bool] = {}# message_id -> is READY message sent

        self.is_BRBdelivered: dict[str, bool] = {}  # message_id -> if this message has gone through SEND ECHO READY and can be BRB delivered
        
        self.Optim1 = parameters.Optim1
        self.Optim2 = parameters.Optim2
        self.Optim3 = parameters.Optim3

    def gen_output_file_path(self, test_name: str = "Bracha_Test"):
        return super().gen_output_file_path(test_name)

    def generate_message(self) -> DolevMessage:
        msg = "".join([random.choice(["uk", "pk", "mkk", "fk"]) for _ in range(6)])
        id = hash(msg)
        return self.generate_send_msg(msg, id, self.node_id, [])

    async def on_start(self):

        # sentEcho = sentReady = delivered = False echos = readys = ∅ clear them if needed
        self.echo_count.clear()
        self.is_echo_sent.clear()
        self.ready_count.clear()
        self.is_ready_sent.clear()
        self.is_BRBdelivered.clear()

        await super().on_start()

    async def on_start_as_starter(self):
        await super().on_start_as_starter()

    # event <Bracha, Broadcast | M >  do
    async def on_broadcast(self, message: DolevMessage) -> None:
        # ⟨Dolev,Broadcast|[Send,m]⟩
        await self.broadcast_message(message.message_id, MessageType.SEND, message)

    
    #event ⟨al,Deliver | p,[SEND,m]⟩
    async def on_send(self, payload: DolevMessage):
        self.msg_log.log(LOG_LEVEL.DEBUG, f"Received a SEND message: {payload.message_id}.")
        # upon event ⟨al,Deliver | p,[SEND,m]⟩ and not sentEcho do
        # threshold = math.ceil((self.f + self.N + 1) / 2)
        # await self.trigger_send_echo(message_id, self.echo_count[message_id], threshold, payload)
        await self.trigger_send_echo(payload.message_id, payload)

    # upon event ⟨al,Deliver | p,[ECHO,m]⟩ do
    async def on_echo(self, payload: DolevMessage):
        self.msg_log.log(LOG_LEVEL.DEBUG, f"Received an ECHO message: {payload.message_id}.")
        
        # echos.insert(p)
        self.increment_echo_count(payload.message_id, payload.source_id)
        # upon event echos.size() ≥ ⌈N+f+1⌉ and not sentReady do
        threshold = math.ceil((self.f + self.N + 1) / 2)
        await self.trigger_send_ready(payload.message_id, len(self.echo_count[payload.message_id]), threshold, payload)
        await self.Optim1_handler(payload.message_id, payload, MessageType.ECHO)


    # upon event ⟨al,Deliver | p,[READY,m]⟩ do
    async def on_ready(self, payload: DolevMessage):
        self.msg_log.log(LOG_LEVEL.DEBUG, f"Received a READY message: {payload.message_id}.")

        self.increment_ready_count(payload.message_id, payload.source_id)
        # upon event readys.size() ≥ f+1 and not sentReady do
        threshold = self.f + 1
        await self.trigger_send_ready(payload.message_id, len(self.ready_count[payload.message_id]), threshold, payload)

        # upon event readys.size() ≥ 2f+1 and not delivered do
        delivered_threshold = (len(self.ready_count.get(payload.message_id)) >= 2*self.f+1) \
                                and self.is_BRBdelivered.get(payload.message_id, False)

        if delivered_threshold:
            self.trigger_Bracha_Delivery(payload)
        
        await self.Optim1_handler(payload.message_id, payload, MessageType.ECHO)

    #  ⟨Dolev,Broadcast|[mType,m]⟩ ensure each msg is broadcasted to all node through dolev protocol
    async def broadcast_message(self, message_id: str, msg_type: MessageType, payload: DolevMessage):
                        
        if msg_type == MessageType.SEND:
            new_msg = self.generate_send_msg(payload.message, payload.message_id+1, self.node_id, [])
        elif msg_type == MessageType.ECHO:
            new_msg = self.generate_echo_msg(payload.message, payload.message_id+1, self.node_id, [])
        elif msg_type == MessageType.READY:
            new_msg = self.generate_ready_msg(payload.message, payload.message_id+1, self.node_id, [])
    
        await super().on_broadcast(new_msg)
        self.msg_log.log(LOG_LEVEL.DEBUG, f"Sent {msg_type.name} messages: {message_id}")

            
    """
    Triggers
    """

    ####trigger ⟨al,Send | q,[ECHO,m]⟩
    # upon event ⟨al, Deliver | p, [SEND, m]⟩ and not sentEcho do
    #   sentEcho = True
    #   forall q do { trigger ⟨al, Send | q, [ECHO, m]⟩ }
    async def trigger_send_echo(self, message_id: str, payload: DolevMessage):
        sent_echo = self.check_if_echo_sent(message_id)
        if not sent_echo:
            self.set_echo_sent_true(message_id)
            await self.broadcast_message(message_id, MessageType.ECHO, payload)

    # trigger ⟨al,Send | q,[READY,m]⟩
    async def trigger_send_ready(self, message_id: str, count: int, threshold: int, payload: DolevMessage):
        """
        Triggers sending a READY message if the conditions are met.
        Ensures the payload is of a valid type and processes it accordingly.
        """
        sent_ready = self.check_if_ready_sent(message_id)
        if not sent_ready and count >= threshold:
            self.set_ready_sent_true(message_id)
            await self.broadcast_message(message_id, MessageType.READY, payload)

    # ⟨Dolev,Deliver | [source,msgType,m]⟩ 
    async def trigger_delivery(self, payload: DolevMessage):

        #self.msg_log.log(LOG_LEVEL.DEBUG, "About to call super().trigger_delivery")
        await super().trigger_delivery(payload)

        payload_type = payload.phase
        if MessageType[payload_type] == MessageType.SEND : 
            await self.on_send(payload)
        elif MessageType[payload_type] == MessageType.ECHO : 
            await self.on_echo(payload)
        elif MessageType[payload_type] == MessageType.READY : 
            # finally, we check if the original msg is BRB delivered
            await self.on_ready(payload)

    # trigger ⟨Bracha,Deliver | s,m⟩
    def trigger_Bracha_Delivery(self, payload):

        payload_og_id = payload.message_id - 3 # place holder to restore the id
        self.is_BRBdelivered.update({payload_og_id: True})
        self.msg_log.log(LOG_LEVEL.INFO, f"Node {self.node_id} BRB Delivered a message: {payload.message_id}.")

        self.write_metrics(payload_og_id)
        
        for msg_id, status in self.is_BRBdelivered.items():
            self.msg_log.log(LOG_LEVEL.DEBUG, f"Delivered Messages: Message ID: {msg_id}, Delivered: {status}")

        self.msg_log.flush()

    """
    Optimizations
    """
    
    async def Optim1_handler(self, message_id: str, payload: DolevMessage, msg_type: MessageType):
        if self.Optim1:
            count = 0
            threshold = 0
            if msg_type == MessageType.ECHO:
                count = self.echo_count[message_id]
                threshold = self.f + 1
                if count >= threshold:
                    if not self.check_if_echo_sent(message_id):
                        self.set_echo_sent_true(message_id)
                        await self.broadcast_message(message_id, MessageType.ECHO, payload, True)
            elif msg_type == MessageType.READY:
                if ():# TODO: 同时满足生成 ECHO 和 READY 消息的条件
                    self.set_echo_sent_true(message_id)
                    self.set_ready_sent_true(message_id)
                    await self.broadcast_message(message_id, MessageType.READY, payload, True)
                elif not self.check_if_echo_sent(message_id):
                    self.set_echo_sent_true(message_id)
                    await self.broadcast_message(message_id, MessageType.ECHO, payload, True)

    """
    Getter & Setter
    """
    def set_echo_sent_true(self, message_id, isSent = True):
        self.is_echo_sent.update({message_id: isSent})

    def set_ready_sent_true(self, message_id , isSent = True):
        self.is_ready_sent.update({message_id: isSent})

    def check_if_echo_sent(self, message_id):
        sent_echo = self.is_echo_sent.get(message_id, False)
        return sent_echo
    
    def check_if_ready_sent(self, message_id):
        return self.is_ready_sent.get(message_id, False)
                
    def increment_echo_count(self, message_id, msg_source_id):
        self.echo_count.setdefault(message_id, set()).add(msg_source_id)

    def increment_ready_count(self, message_id, msg_source_id):
        self.ready_count.setdefault(message_id, set()).add(msg_source_id)
        
    def generate_send_msg(self,message: str, message_id: str, source_id: str, destination: List[str]):
        return DolevMessage(message, message_id, source_id, destination, "SEND")
    
    def generate_echo_msg(self,message: str, message_id: str, source_id: str, destination: List[str]):
        return DolevMessage(message, message_id, source_id, destination, "ECHO")
    
    def generate_ready_msg(self,message: str, message_id: str, source_id: str, destination: List[str]):
        return DolevMessage(message, message_id, source_id, destination, "READY")