"""
==================================================
POW_DOS_PROTECTION.PY - Proof-of-Work DoS Defense
==================================================
Adaptive PoW challenges to prevent DoS attacks
Hashcash-style with dynamic difficulty adjustment
"""
import hashlib
import time
import struct
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
import random


# ==================== CONSTANTS ====================

DEFAULT_DIFFICULTY = 16  # Leading zero bits required
MAX_DIFFICULTY = 24
MIN_DIFFICULTY = 8
TARGET_SOLVE_TIME = 1.0  # Target seconds to solve
DIFFICULTY_ADJUSTMENT_WINDOW = 100  # Adjust every N challenges
CHALLENGE_EXPIRY = 300  # Challenge valid for 5 minutes


# ==================== DATA STRUCTURES ====================

@dataclass
class PoWChallenge:
    """
    Proof-of-Work challenge

    Format: Find nonce such that:
    SHA256(challenge || nonce) has N leading zero bits
    """
    challenge_id: str
    resource: str  # Protected resource (e.g., "/api/endpoint")
    timestamp: float
    difficulty: int  # Leading zero bits required
    salt: bytes  # Random salt

    def to_dict(self) -> Dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "resource": self.resource,
            "timestamp": self.timestamp,
            "difficulty": self.difficulty,
            "salt": self.salt.hex()
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PoWChallenge":
        return PoWChallenge(
            challenge_id=d["challenge_id"],
            resource=d["resource"],
            timestamp=d["timestamp"],
            difficulty=d["difficulty"],
            salt=bytes.fromhex(d["salt"])
        )

    def is_expired(self) -> bool:
        """Check if challenge has expired"""
        return (time.time() - self.timestamp) > CHALLENGE_EXPIRY


@dataclass
class PoWSolution:
    """Solution to PoW challenge"""
    challenge_id: str
    nonce: int
    hash_result: bytes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "nonce": self.nonce,
            "hash": self.hash_result.hex()
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PoWSolution":
        return PoWSolution(
            challenge_id=d["challenge_id"],
            nonce=d["nonce"],
            hash_result=bytes.fromhex(d["hash"])
        )


# ==================== POW ENGINE ====================

class PoWEngine:
    """
    Proof-of-Work computation engine

    Supports multiple hash functions and difficulty levels
    """

    @staticmethod
    def compute_hash(challenge: PoWChallenge, nonce: int) -> bytes:
        """
        Compute hash for challenge + nonce

        Hash(challenge_id || salt || nonce || timestamp)
        """
        data = (
            challenge.challenge_id.encode() +
            challenge.salt +
            struct.pack("!Q", nonce) +
            struct.pack("!d", challenge.timestamp)
        )
        return hashlib.sha256(data).digest()

    @staticmethod
    def check_difficulty(hash_result: bytes, difficulty: int) -> bool:
        """
        Check if hash meets difficulty requirement

        Counts leading zero bits in hash
        """
        # Convert hash to integer
        hash_int = int.from_bytes(hash_result, 'big')

        # Count leading zeros
        if hash_int == 0:
            return True

        leading_zeros = 256 - hash_int.bit_length()

        return leading_zeros >= difficulty

    @staticmethod
    def solve(challenge: PoWChallenge, max_attempts: int = 10_000_000) -> Optional[PoWSolution]:
        """
        Solve PoW challenge

        Brute force search for valid nonce
        """
        start_time = time.time()

        for nonce in range(max_attempts):
            hash_result = PoWEngine.compute_hash(challenge, nonce)

            if PoWEngine.check_difficulty(hash_result, challenge.difficulty):
                solve_time = time.time() - start_time
                return PoWSolution(
                    challenge_id=challenge.challenge_id,
                    nonce=nonce,
                    hash_result=hash_result
                )

            # Give up if challenge expired
            if challenge.is_expired():
                break

        return None

    @staticmethod
    def verify(challenge: PoWChallenge, solution: PoWSolution) -> bool:
        """
        Verify PoW solution

        Fast verification (single hash)
        """
        # Check challenge ID matches
        if challenge.challenge_id != solution.challenge_id:
            return False

        # Check challenge not expired
        if challenge.is_expired():
            return False

        # Recompute hash
        computed_hash = PoWEngine.compute_hash(challenge, solution.nonce)

        # Verify hash matches
        if computed_hash != solution.hash_result:
            return False

        # Verify difficulty
        return PoWEngine.check_difficulty(computed_hash, challenge.difficulty)


# ==================== ADAPTIVE DIFFICULTY ====================

class AdaptiveDifficulty:
    """
    Dynamically adjusts PoW difficulty based on:
    - Current load
    - Attack patterns
    - Client solve times
    """

    def __init__(self, base_difficulty: int = DEFAULT_DIFFICULTY):
        self.base_difficulty = base_difficulty
        self.current_difficulty = base_difficulty

        # Statistics
        self.solve_times: list = []
        self.challenge_count = 0
        self.failed_verifications = 0

        # Attack detection
        self.recent_requests: Dict[str, list] = {}  # IP -> timestamps

    def get_difficulty(self, client_ip: str) -> int:
        """
        Get difficulty for client

        Increases difficulty for:
        - High request rate
        - Failed verifications
        - Detected attack patterns
        """
        difficulty = self.current_difficulty

        # Check client request rate
        request_rate = self._get_request_rate(client_ip)

        if request_rate > 10:  # >10 req/sec
            difficulty += 4
        elif request_rate > 5:
            difficulty += 2

        # Check failed verification rate
        if self.challenge_count > 0:
            fail_rate = self.failed_verifications / self.challenge_count
            if fail_rate > 0.5:  # >50% failures
                difficulty += 3

        # Cap difficulty
        return min(difficulty, MAX_DIFFICULTY)

    def record_solve_time(self, solve_time: float):
        """Record client solve time"""
        self.solve_times.append(solve_time)
        self.challenge_count += 1

        # Keep last N samples
        if len(self.solve_times) > DIFFICULTY_ADJUSTMENT_WINDOW:
            self.solve_times.pop(0)

        # Adjust difficulty periodically
        if self.challenge_count % DIFFICULTY_ADJUSTMENT_WINDOW == 0:
            self._adjust_difficulty()

    def record_verification_failure(self):
        """Record failed verification"""
        self.failed_verifications += 1

    def record_request(self, client_ip: str):
        """Record client request for rate limiting"""
        now = time.time()

        if client_ip not in self.recent_requests:
            self.recent_requests[client_ip] = []

        # Add timestamp
        self.recent_requests[client_ip].append(now)

        # Clean old timestamps (>60 seconds)
        self.recent_requests[client_ip] = [
            ts for ts in self.recent_requests[client_ip]
            if now - ts < 60
        ]

    def _get_request_rate(self, client_ip: str) -> float:
        """Get client request rate (req/sec)"""
        if client_ip not in self.recent_requests:
            return 0.0

        timestamps = self.recent_requests[client_ip]
        if len(timestamps) < 2:
            return 0.0

        time_span = timestamps[-1] - timestamps[0]
        return len(timestamps) / max(time_span, 1.0)

    def _adjust_difficulty(self):
        """Adjust base difficulty based on solve times"""
        if not self.solve_times:
            return

        avg_solve_time = sum(self.solve_times) / len(self.solve_times)

        # Target is 1 second
        if avg_solve_time < TARGET_SOLVE_TIME * 0.5:
            # Too fast, increase difficulty
            self.current_difficulty = min(self.current_difficulty + 1, MAX_DIFFICULTY)
        elif avg_solve_time > TARGET_SOLVE_TIME * 2.0:
            # Too slow, decrease difficulty
            self.current_difficulty = max(self.current_difficulty - 1, MIN_DIFFICULTY)

    def get_stats(self) -> Dict[str, Any]:
        """Get difficulty statistics"""
        avg_solve_time = (
            sum(self.solve_times) / len(self.solve_times)
            if self.solve_times else 0.0
        )

        return {
            "base_difficulty": self.base_difficulty,
            "current_difficulty": self.current_difficulty,
            "challenge_count": self.challenge_count,
            "failed_verifications": self.failed_verifications,
            "avg_solve_time_ms": round(avg_solve_time * 1000, 2),
            "active_clients": len(self.recent_requests)
        }


# ==================== POW MANAGER ====================

class PoWManager:
    """
    Manages PoW challenges and verifications

    Integrates with web server for DoS protection
    """

    def __init__(self, base_difficulty: int = DEFAULT_DIFFICULTY):
        self.adaptive_difficulty = AdaptiveDifficulty(base_difficulty)
        self.active_challenges: Dict[str, PoWChallenge] = {}
        self.verified_solutions: Dict[str, float] = {}  # challenge_id -> verify_time

    def create_challenge(self, resource: str, client_ip: str) -> PoWChallenge:
        """
        Create new PoW challenge for client

        Args:
            resource: Protected resource path
            client_ip: Client IP address

        Returns:
            PoWChallenge object
        """
        # Record request
        self.adaptive_difficulty.record_request(client_ip)

        # Generate challenge
        challenge_id = hashlib.sha256(
            f"{client_ip}{resource}{time.time()}{random.random()}".encode()
        ).hexdigest()[:16]

        salt = hashlib.sha256(str(random.random()).encode()).digest()[:16]

        difficulty = self.adaptive_difficulty.get_difficulty(client_ip)

        challenge = PoWChallenge(
            challenge_id=challenge_id,
            resource=resource,
            timestamp=time.time(),
            difficulty=difficulty,
            salt=salt
        )

        self.active_challenges[challenge_id] = challenge

        return challenge

    def verify_solution(self, solution: PoWSolution) -> bool:
        """
        Verify client solution

        Returns True if valid, False otherwise
        """
        # Get challenge
        challenge = self.active_challenges.get(solution.challenge_id)
        if not challenge:
            self.adaptive_difficulty.record_verification_failure()
            return False

        # Verify solution
        start_time = time.time()
        is_valid = PoWEngine.verify(challenge, solution)
        verify_time = time.time() - start_time

        if is_valid:
            # Record solve time (client timestamp to now)
            solve_time = time.time() - challenge.timestamp
            self.adaptive_difficulty.record_solve_time(solve_time)

            # Mark as verified
            self.verified_solutions[solution.challenge_id] = time.time()

            # Remove from active
            del self.active_challenges[solution.challenge_id]
        else:
            self.adaptive_difficulty.record_verification_failure()

        return is_valid

    def is_verified(self, challenge_id: str) -> bool:
        """Check if challenge has been verified"""
        return challenge_id in self.verified_solutions

    def cleanup_expired(self):
        """Remove expired challenges"""
        now = time.time()

        # Clean active challenges
        expired = [
            cid for cid, challenge in self.active_challenges.items()
            if challenge.is_expired()
        ]
        for cid in expired:
            del self.active_challenges[cid]

        # Clean verified solutions (keep for 10 minutes)
        expired_verified = [
            cid for cid, verify_time in self.verified_solutions.items()
            if now - verify_time > 600
        ]
        for cid in expired_verified:
            del self.verified_solutions[cid]

    def get_stats(self) -> Dict[str, Any]:
        """Get PoW manager statistics"""
        stats = self.adaptive_difficulty.get_stats()
        stats.update({
            "active_challenges": len(self.active_challenges),
            "verified_solutions": len(self.verified_solutions)
        })
        return stats


# ==================== CLIENT HELPER ====================

async def solve_challenge_async(challenge: PoWChallenge) -> Optional[PoWSolution]:
    """
    Solve challenge asynchronously (non-blocking)

    Runs PoW computation in thread pool
    """
    import asyncio
    import concurrent.futures

    loop = asyncio.get_event_loop()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        solution = await loop.run_in_executor(
            executor,
            PoWEngine.solve,
            challenge
        )

    return solution


# ==================== EXPORT ====================

__all__ = [
    'PoWChallenge',
    'PoWSolution',
    'PoWEngine',
    'PoWManager',
    'AdaptiveDifficulty',
    'solve_challenge_async'
]


if __name__ == "__main__":
    print("=== POW DOS PROTECTION SELF-TEST ===")

    # Test PoW engine
    manager = PoWManager(base_difficulty=12)  # Lower for testing

    # Create challenge
    challenge = manager.create_challenge("/api/secret", "192.168.1.100")
    print(f"✓ Challenge created: {challenge.challenge_id}")
    print(f"  Difficulty: {challenge.difficulty}")

    # Solve challenge
    print("  Solving...")
    start_time = time.time()
    solution = PoWEngine.solve(challenge, max_attempts=1_000_000)
    solve_time = time.time() - start_time

    if solution:
        print(f"✓ Solution found in {solve_time:.2f}s")
        print(f"  Nonce: {solution.nonce}")
        print(f"  Hash: {solution.hash_result.hex()[:16]}...")

        # Verify solution
        is_valid = manager.verify_solution(solution)
        print(f"✓ Verification: {'VALID' if is_valid else 'INVALID'}")
    else:
        print("✗ No solution found")

    # Test adaptive difficulty
    print("\nTesting adaptive difficulty...")
    for i in range(10):
        challenge = manager.create_challenge("/api/test", "192.168.1.100")
        solution = PoWEngine.solve(challenge, max_attempts=100_000)
        if solution:
            manager.verify_solution(solution)

    stats = manager.get_stats()
    print(f"✓ Stats after 10 challenges:")
    print(f"  Current difficulty: {stats['current_difficulty']}")
    print(f"  Avg solve time: {stats['avg_solve_time_ms']:.0f}ms")
    print(f"  Verified: {stats['verified_solutions']}")

    print("\n✅ PoW DoS protection test complete")
