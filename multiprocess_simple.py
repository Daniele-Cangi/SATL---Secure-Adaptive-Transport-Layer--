"""
MULTIPROCESS_SIMPLE.PY - Windows-Compatible Multiprocessing
Uses concurrent.futures.ProcessPoolExecutor (Windows-safe)
"""
import concurrent.futures
import asyncio
from typing import Optional, List, Dict, Any
from onion_crypto import OnionCrypto


def encrypt_worker(data: bytes, nodes: List[Dict[str, Any]]) -> bytes:
    """Worker function for encryption (must be picklable)"""
    crypto = OnionCrypto()
    if nodes:
        layers = crypto.create_circuit(nodes)
        return crypto.encrypt_onion(data)
    else:
        # Mock encryption for testing
        return data + b"_encrypted"


class SimpleParallelProcessor:
    """Simple parallel processor using ProcessPoolExecutor"""

    def __init__(self, worker_count: int = 4):
        self.executor = concurrent.futures.ProcessPoolExecutor(max_workers=worker_count)
        self.worker_count = worker_count

    async def encrypt_async(self, data: bytes, nodes: List[Dict[str, Any]]) -> Optional[bytes]:
        """Encrypt data in parallel"""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                self.executor,
                encrypt_worker,
                data,
                nodes
            )
            return result
        except Exception as e:
            print(f"Encryption error: {e}")
            return None

    def shutdown(self):
        """Shutdown executor"""
        self.executor.shutdown(wait=True)

    def get_stats(self) -> Dict[str, Any]:
        """Get stats"""
        return {
            "worker_count": self.worker_count,
            "active_workers": self.worker_count,
            "total_processed": 0,
            "avg_cpu_percent": 0.0
        }


if __name__ == "__main__":
    # Test
    async def test():
        processor = SimpleParallelProcessor(worker_count=4)
        try:
            tasks = [
                processor.encrypt_async(f"Test {i}".encode() * 10, [])
                for i in range(10)
            ]
            results = await asyncio.gather(*tasks)
            success = sum(1 for r in results if r)
            print(f"[OK] {success}/10 tasks completed")
        finally:
            processor.shutdown()

    asyncio.run(test())
