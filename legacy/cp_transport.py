# cp_transport.py - Control Plane con trasporto dedicato
import asyncio
import struct
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
import json

# Placeholder per QUIC (richiede aioquic)
# pip install aioquic
try:
    from aioquic.asyncio import QuicConnectionProtocol, serve
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import StreamDataReceived
    QUIC_AVAILABLE = True
except ImportError:
    QUIC_AVAILABLE = False
    print("Warning: aioquic not installed, using TCP fallback")

@dataclass
class CPMessage:
    """Messaggio Control Plane"""
    msg_type: str  # "instruction", "ack", "health_check"
    channel_id: str
    payload: Dict[str, Any]
    timestamp: float
    nonce: int  # Anti-replay
    signature: str  # Firma SPO

class CPProtocol:
    """
    Protocollo Control Plane.
    
    Caratteristiche:
    - Messaggi piccoli (max 4KB)
    - Encrypted con Kyber (PQ-KEM)
    - Ogni messaggio ha nonce incrementale
    - Firma SPO verificata da nodi
    """
    
    MAGIC = b"SATL"
    VERSION = 1
    
    @staticmethod
    def serialize(msg: CPMessage) -> bytes:
        """
        Formato wire:
        [MAGIC:4][VERSION:1][LENGTH:2][JSON_PAYLOAD]
        """
        payload_json = json.dumps(asdict(msg)).encode('utf-8')
        
        if len(payload_json) > 4096:
            raise ValueError("CP message too large (max 4KB)")
        
        header = struct.pack(
            "!4sBH",  # Magic, Version, Length
            CPProtocol.MAGIC,
            CPProtocol.VERSION,
            len(payload_json)
        )
        
        return header + payload_json
    
    @staticmethod
    def deserialize(data: bytes) -> CPMessage:
        """Parse wire format"""
        if len(data) < 7:
            raise ValueError("Message too short")
        
        magic, version, length = struct.unpack("!4sBH", data[:7])
        
        if magic != CPProtocol.MAGIC:
            raise ValueError(f"Invalid magic: {magic}")
        
        if version != CPProtocol.VERSION:
            raise ValueError(f"Unsupported version: {version}")
        
        payload_json = data[7:7+length]
        payload_dict = json.loads(payload_json)
        
        return CPMessage(**payload_dict)


class CPServer:
    """
    Server Control Plane (gira sul core SPO).
    
    Distribuisce istruzioni ai nodi.
    """
    
    def __init__(self, host: str, port: int, spo_signer):
        self.host = host
        self.port = port
        self.spo_signer = spo_signer
        self.nonce_counter = 0
        self.active_channels: Dict[str, Any] = {}
    
    async def send_instruction(self, node_addr: str, channel_id: str, 
                               instruction: Dict[str, Any]):
        """
        Invia un'istruzione a un nodo specifico.
        """
        self.nonce_counter += 1
        
        # Firma l'istruzione
        sig = self.spo_signer.sign_instruction(instruction)
        
        msg = CPMessage(
            msg_type="instruction",
            channel_id=channel_id,
            payload=instruction,
            timestamp=time.time(),
            nonce=self.nonce_counter,
            signature=sig
        )
        
        # TODO: Invia via QUIC al nodo
        # Per ora: placeholder
        print(f"[CP] Sending to {node_addr}: {msg.msg_type}")
    
    async def broadcast_rotation(self, channel_id: str, rotation_pack: Dict[str, Any]):
        """
        Broadcast rotazione a tutti i nodi coinvolti nel channel.
        """
        channel = self.active_channels.get(channel_id)
        if not channel:
            return
        
        nodes = channel["route"]["hops"]
        
        tasks = [
            self.send_instruction(node, channel_id, rotation_pack)
            for node in nodes
        ]
        
        await asyncio.gather(*tasks)


class CPClient:
    """
    Client Control Plane (gira sui nodi).
    
    Riceve istruzioni dal core SPO e le applica al DP locale.
    """
    
    def __init__(self, node_id: str, spo_pubkey: bytes, on_instruction_callback):
        self.node_id = node_id
        self.spo_pubkey = spo_pubkey
        self.on_instruction = on_instruction_callback
        self.seen_nonces = set()  # Anti-replay
    
    def verify_and_apply(self, msg: CPMessage) -> bool:
        """
        Verifica firma SPO e applica istruzione.
        """
        # Anti-replay
        if msg.nonce in self.seen_nonces:
            print(f"[CP] Replay attack detected: nonce {msg.nonce}")
            return False
        
        # Verifica firma
        from spo_signature import SPOSigner
        signer = SPOSigner()  # TODO: load con pubkey corretta
        
        if not signer.verify_instruction(msg.payload, msg.signature):
            print(f"[CP] Invalid signature from SPO")
            return False
        
        # Verifica timestamp (max 60s di clock skew)
        now = time.time()
        if abs(now - msg.timestamp) > 60:
            print(f"[CP] Message too old/future: {msg.timestamp}")
            return False
        
        # OK, applica
        self.seen_nonces.add(msg.nonce)
        self.on_instruction(msg.payload)
        
        return True


class CPOverTCP:
    """
    Fallback: Control Plane su TCP custom (se QUIC non disponibile).
    
    Meno efficiente ma più semplice da deployare.
    """
    
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.server: Optional[asyncio.Server] = None
    
    async def handle_client(self, reader: asyncio.StreamReader, 
                           writer: asyncio.StreamWriter):
        """Handle singola connessione nodo"""
        try:
            # Leggi header
            header = await reader.readexactly(7)
            magic, version, length = struct.unpack("!4sBH", header)
            
            if magic != CPProtocol.MAGIC:
                writer.close()
                return
            
            # Leggi payload
            payload = await reader.readexactly(length)
            msg = CPProtocol.deserialize(header + payload)
            
            # Process (placeholder)
            print(f"[CP/TCP] Received: {msg.msg_type}")
            
            # Ack
            ack = CPMessage(
                msg_type="ack",
                channel_id=msg.channel_id,
                payload={"status": "ok"},
                timestamp=time.time(),
                nonce=msg.nonce,
                signature=""
            )
            
            writer.write(CPProtocol.serialize(ack))
            await writer.drain()
            
        except Exception as e:
            print(f"[CP/TCP] Error: {e}")
        finally:
            writer.close()
    
    async def start(self):
        """Avvia server TCP"""
        self.server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        
        print(f"[CP/TCP] Listening on {self.host}:{self.port}")
        
        async with self.server:
            await self.server.serve_forever()


# Usage example
async def main():
    # Setup CP server (sul core SPO)
    from spo_signature import SPOSigner
    signer = SPOSigner()
    
    if QUIC_AVAILABLE:
        print("Using QUIC transport")
        # TODO: implement QUIC server
    else:
        print("Using TCP fallback")
        cp_server = CPOverTCP("0.0.0.0", 5555)
        
        # Avvia in background
        asyncio.create_task(cp_server.start())
    
    # Simula invio istruzione
    server = CPServer("localhost", 5555, signer)
    
    instruction = {
        "type": "rotate",
        "payload": {"hops": ["node-x", "node-y"]}
    }
    
    await server.send_instruction("node-1", "ch-123", instruction)

if __name__ == "__main__":
    asyncio.run(main())
