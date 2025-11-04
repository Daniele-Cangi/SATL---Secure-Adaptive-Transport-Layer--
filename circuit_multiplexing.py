"""
================================================
CIRCUIT_MULTIPLEXING.PY - Stream Multiplexing
================================================
Multiple data streams over single circuit
Tor-style stream isolation and congestion control
"""
import asyncio
import time
import hashlib
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from collections import deque
import struct


# ==================== CONSTANTS ====================

MAX_STREAM_ID = 2**16 - 1  # 16-bit stream IDs
STREAM_WINDOW_SIZE = 500  # Flow control window (cells)
CIRCUIT_WINDOW_SIZE = 1000  # Circuit-level window
CELL_SIZE = 512  # Fixed cell size (bytes)
STREAM_TIMEOUT = 60.0  # Stream idle timeout (seconds)


# ==================== CELL TYPES ====================

class CellType:
    """Circuit cell types (Tor-compatible)"""
    DATA = 0x02  # Data cell
    BEGIN = 0x03  # Open stream
    END = 0x04  # Close stream
    SENDME = 0x05  # Flow control
    RELAY = 0x06  # Relay cell
    CREATE = 0x07  # Create circuit
    CREATED = 0x08  # Circuit created
    DESTROY = 0x09  # Destroy circuit


# ==================== DATA STRUCTURES ====================

@dataclass
class Cell:
    """
    Fixed-size circuit cell (512 bytes total)

    Format:
    - Circuit ID: 4 bytes
    - Command: 1 byte
    - Stream ID: 2 bytes (for relay cells)
    - Length: 2 bytes
    - Payload: up to 503 bytes
    """
    circuit_id: int
    command: int
    stream_id: int = 0
    payload: bytes = b""

    def to_bytes(self) -> bytes:
        """Serialize to wire format"""
        # Header: circuit_id (4) + command (1) + stream_id (2) + length (2) = 9 bytes
        header = struct.pack(
            "!IBHrH",
            self.circuit_id,
            self.command,
            self.stream_id,
            len(self.payload)
        )

        # Pad payload to fixed cell size
        padded_payload = self.payload + b'\x00' * (CELL_SIZE - 9 - len(self.payload))

        return header + padded_payload[:CELL_SIZE - 9]

    @staticmethod
    def from_bytes(data: bytes) -> "Cell":
        """Deserialize from wire format"""
        if len(data) < CELL_SIZE:
            raise ValueError(f"Invalid cell size: {len(data)}")

        circuit_id, command, stream_id, length = struct.unpack("!IBHH", data[:9])
        payload = data[9:9+length]

        return Cell(
            circuit_id=circuit_id,
            command=command,
            stream_id=stream_id,
            payload=payload
        )


@dataclass
class Stream:
    """
    Multiplexed stream within a circuit

    Each stream is an independent data flow
    (e.g., HTTP request, DNS query, etc.)
    """
    stream_id: int
    circuit_id: int
    state: str = "OPEN"  # OPEN, CLOSED, BUFFERING
    send_window: int = STREAM_WINDOW_SIZE
    recv_window: int = STREAM_WINDOW_SIZE
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # Buffers
    send_queue: deque = field(default_factory=deque)
    recv_queue: deque = field(default_factory=deque)

    # Callbacks
    on_data: Optional[Callable[[bytes], None]] = None
    on_close: Optional[Callable[[], None]] = None

    def is_timeout(self) -> bool:
        """Check if stream has timed out"""
        return (time.time() - self.last_activity) > STREAM_TIMEOUT

    def can_send(self) -> bool:
        """Check if stream can send (flow control)"""
        return self.send_window > 0 and self.state == "OPEN"

    def queue_data(self, data: bytes):
        """Queue data for sending"""
        # Split into cell-sized chunks
        offset = 0
        max_payload = CELL_SIZE - 9  # Cell header size

        while offset < len(data):
            chunk = data[offset:offset + max_payload]
            self.send_queue.append(chunk)
            offset += len(chunk)

        self.last_activity = time.time()

    def receive_data(self, data: bytes):
        """Receive data from circuit"""
        self.recv_queue.append(data)
        self.last_activity = time.time()

        # Trigger callback if set
        if self.on_data:
            self.on_data(data)

    def close(self):
        """Close stream"""
        self.state = "CLOSED"
        if self.on_close:
            self.on_close()


# ==================== CIRCUIT ====================

class Circuit:
    """
    Multiplexed circuit with multiple streams

    Manages:
    - Stream creation/destruction
    - Flow control (circuit + stream level)
    - Cell routing
    - Congestion control
    """

    def __init__(self, circuit_id: int):
        self.circuit_id = circuit_id
        self.streams: Dict[int, Stream] = {}
        self.next_stream_id = 1

        # Circuit-level flow control
        self.circuit_send_window = CIRCUIT_WINDOW_SIZE
        self.circuit_recv_window = CIRCUIT_WINDOW_SIZE

        # Queues
        self.outbound_cells: deque = deque()
        self.pending_streams: Dict[int, asyncio.Future] = {}

        # State
        self.created_at = time.time()
        self.last_activity = time.time()
        self.is_active = True

        # Stats
        self.cells_sent = 0
        self.cells_received = 0
        self.bytes_sent = 0
        self.bytes_received = 0

    def create_stream(self) -> int:
        """
        Create new stream on this circuit

        Returns stream_id
        """
        stream_id = self.next_stream_id
        self.next_stream_id = (self.next_stream_id + 1) % MAX_STREAM_ID

        if stream_id == 0:  # Reserved
            stream_id = 1
            self.next_stream_id = 2

        stream = Stream(
            stream_id=stream_id,
            circuit_id=self.circuit_id
        )

        self.streams[stream_id] = stream
        self.last_activity = time.time()

        # Send BEGIN cell
        begin_cell = Cell(
            circuit_id=self.circuit_id,
            command=CellType.BEGIN,
            stream_id=stream_id,
            payload=b"BEGIN"
        )
        self.outbound_cells.append(begin_cell)

        return stream_id

    def close_stream(self, stream_id: int):
        """Close a stream"""
        stream = self.streams.get(stream_id)
        if not stream:
            return

        stream.close()

        # Send END cell
        end_cell = Cell(
            circuit_id=self.circuit_id,
            command=CellType.END,
            stream_id=stream_id,
            payload=b"END"
        )
        self.outbound_cells.append(end_cell)

        # Clean up after delay (allow pending cells to flush)
        asyncio.create_task(self._cleanup_stream(stream_id))

    async def _cleanup_stream(self, stream_id: int):
        """Delayed stream cleanup"""
        await asyncio.sleep(1.0)
        if stream_id in self.streams:
            del self.streams[stream_id]

    def send_data(self, stream_id: int, data: bytes) -> bool:
        """
        Send data on stream

        Returns True if queued, False if blocked by flow control
        """
        stream = self.streams.get(stream_id)
        if not stream or not stream.can_send():
            return False

        # Flow control check
        if self.circuit_send_window <= 0:
            return False

        # Queue data in stream
        stream.queue_data(data)
        self.last_activity = time.time()

        return True

    def process_outbound(self) -> Optional[Cell]:
        """
        Get next outbound cell to send

        Implements fair queuing across streams
        """
        if not self.outbound_cells and not self.streams:
            return None

        # Check circuit-level flow control
        if self.circuit_send_window <= 0:
            return None

        # Check for queued cells first
        if self.outbound_cells:
            cell = self.outbound_cells.popleft()
            self.circuit_send_window -= 1
            self.cells_sent += 1
            self.bytes_sent += len(cell.payload)
            return cell

        # Round-robin across streams
        for stream in list(self.streams.values()):
            if stream.send_queue and stream.can_send():
                payload = stream.send_queue.popleft()

                cell = Cell(
                    circuit_id=self.circuit_id,
                    command=CellType.DATA,
                    stream_id=stream.stream_id,
                    payload=payload
                )

                stream.send_window -= 1
                self.circuit_send_window -= 1
                self.cells_sent += 1
                self.bytes_sent += len(payload)

                # Send SENDME if window low
                if stream.send_window < STREAM_WINDOW_SIZE // 2:
                    self._send_stream_sendme(stream.stream_id)

                return cell

        return None

    def process_inbound(self, cell: Cell):
        """Process incoming cell"""
        self.cells_received += 1
        self.bytes_received += len(cell.payload)
        self.last_activity = time.time()

        # Circuit-level flow control
        self.circuit_recv_window -= 1
        if self.circuit_recv_window < CIRCUIT_WINDOW_SIZE // 2:
            self._send_circuit_sendme()

        # Handle by cell type
        if cell.command == CellType.DATA:
            self._handle_data_cell(cell)
        elif cell.command == CellType.BEGIN:
            self._handle_begin_cell(cell)
        elif cell.command == CellType.END:
            self._handle_end_cell(cell)
        elif cell.command == CellType.SENDME:
            self._handle_sendme_cell(cell)
        elif cell.command == CellType.DESTROY:
            self._handle_destroy_cell(cell)

    def _handle_data_cell(self, cell: Cell):
        """Handle DATA cell"""
        stream = self.streams.get(cell.stream_id)
        if stream and stream.state == "OPEN":
            stream.receive_data(cell.payload)

            # Update stream flow control
            stream.recv_window -= 1
            if stream.recv_window < STREAM_WINDOW_SIZE // 2:
                self._send_stream_sendme(cell.stream_id)

    def _handle_begin_cell(self, cell: Cell):
        """Handle BEGIN cell (create stream)"""
        if cell.stream_id not in self.streams:
            stream = Stream(
                stream_id=cell.stream_id,
                circuit_id=self.circuit_id
            )
            self.streams[cell.stream_id] = stream

    def _handle_end_cell(self, cell: Cell):
        """Handle END cell (close stream)"""
        if cell.stream_id in self.streams:
            self.streams[cell.stream_id].close()

    def _handle_sendme_cell(self, cell: Cell):
        """Handle SENDME cell (flow control)"""
        if cell.stream_id == 0:
            # Circuit-level SENDME
            self.circuit_send_window += 100
        else:
            # Stream-level SENDME
            stream = self.streams.get(cell.stream_id)
            if stream:
                stream.send_window += 50

    def _handle_destroy_cell(self, cell: Cell):
        """Handle DESTROY cell (circuit teardown)"""
        self.is_active = False
        for stream in self.streams.values():
            stream.close()

    def _send_stream_sendme(self, stream_id: int):
        """Send stream-level SENDME"""
        sendme_cell = Cell(
            circuit_id=self.circuit_id,
            command=CellType.SENDME,
            stream_id=stream_id,
            payload=b""
        )
        self.outbound_cells.append(sendme_cell)

    def _send_circuit_sendme(self):
        """Send circuit-level SENDME"""
        sendme_cell = Cell(
            circuit_id=self.circuit_id,
            command=CellType.SENDME,
            stream_id=0,
            payload=b""
        )
        self.outbound_cells.append(sendme_cell)

    def cleanup_idle_streams(self):
        """Remove idle/closed streams"""
        to_remove = []
        for stream_id, stream in self.streams.items():
            if stream.state == "CLOSED" or stream.is_timeout():
                to_remove.append(stream_id)

        for stream_id in to_remove:
            del self.streams[stream_id]

    def get_stats(self) -> Dict[str, Any]:
        """Get circuit statistics"""
        return {
            "circuit_id": self.circuit_id,
            "stream_count": len(self.streams),
            "cells_sent": self.cells_sent,
            "cells_received": self.cells_received,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "send_window": self.circuit_send_window,
            "recv_window": self.circuit_recv_window,
            "age_seconds": time.time() - self.created_at
        }


# ==================== CIRCUIT POOL ====================

class CircuitPool:
    """
    Pool of circuits for load balancing

    Manages multiple circuits and distributes streams
    """

    def __init__(self, max_circuits: int = 10):
        self.circuits: Dict[int, Circuit] = {}
        self.next_circuit_id = 1
        self.max_circuits = max_circuits

    def create_circuit(self) -> Circuit:
        """Create new circuit"""
        circuit_id = self.next_circuit_id
        self.next_circuit_id += 1

        circuit = Circuit(circuit_id)
        self.circuits[circuit_id] = circuit

        return circuit

    def get_best_circuit(self) -> Optional[Circuit]:
        """
        Get best circuit for new stream

        Selection criteria:
        - Active circuit
        - Low stream count
        - Good flow control window
        """
        active_circuits = [
            c for c in self.circuits.values()
            if c.is_active and c.circuit_send_window > 100
        ]

        if not active_circuits:
            return None

        # Select circuit with fewest streams
        return min(active_circuits, key=lambda c: len(c.streams))

    def cleanup(self):
        """Remove dead circuits and idle streams"""
        to_remove = []

        for circuit_id, circuit in self.circuits.items():
            circuit.cleanup_idle_streams()

            # Remove circuit if dead or too old
            age = time.time() - circuit.created_at
            if not circuit.is_active or age > 600:  # 10 minutes max
                to_remove.append(circuit_id)

        for circuit_id in to_remove:
            del self.circuits[circuit_id]

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics"""
        total_streams = sum(len(c.streams) for c in self.circuits.values())
        total_bytes = sum(c.bytes_sent + c.bytes_received for c in self.circuits.values())

        return {
            "circuit_count": len(self.circuits),
            "active_circuits": sum(1 for c in self.circuits.values() if c.is_active),
            "total_streams": total_streams,
            "total_bytes": total_bytes,
            "circuits": [c.get_stats() for c in self.circuits.values()]
        }


# ==================== EXPORT ====================

__all__ = [
    'Cell',
    'CellType',
    'Stream',
    'Circuit',
    'CircuitPool',
    'CELL_SIZE'
]


if __name__ == "__main__":
    print("=== CIRCUIT MULTIPLEXING SELF-TEST ===")

    # Create circuit pool
    pool = CircuitPool(max_circuits=5)

    # Create circuit
    circuit = pool.create_circuit()
    print(f"✓ Circuit created: {circuit.circuit_id}")

    # Create streams
    stream1_id = circuit.create_stream()
    stream2_id = circuit.create_stream()
    print(f"✓ Streams created: {stream1_id}, {stream2_id}")

    # Send data on streams
    data1 = b"Hello from stream 1" * 100
    data2 = b"Data from stream 2" * 100

    circuit.send_data(stream1_id, data1)
    circuit.send_data(stream2_id, data2)
    print(f"✓ Data queued on streams")

    # Process outbound cells
    cells_sent = 0
    while True:
        cell = circuit.process_outbound()
        if not cell:
            break
        cells_sent += 1

        # Simulate receiving SENDME
        if cells_sent % 50 == 0:
            sendme = Cell(
                circuit_id=circuit.circuit_id,
                command=CellType.SENDME,
                stream_id=0,
                payload=b""
            )
            circuit.process_inbound(sendme)

    print(f"✓ Processed {cells_sent} cells")

    # Get stats
    stats = circuit.get_stats()
    print(f"\nCircuit Stats:")
    print(f"  Streams: {stats['stream_count']}")
    print(f"  Cells sent: {stats['cells_sent']}")
    print(f"  Bytes sent: {stats['bytes_sent']}")

    print("\n✅ Circuit multiplexing test complete")
