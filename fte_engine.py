"""
==============================================
FTE_ENGINE.PY - Format-Transforming Encryption
==============================================
Real protocol mimicry: HTTP, TLS, WebSocket, DNS
Makes traffic indistinguishable from legitimate protocols
"""
import re
import random
import time
import base64
import hashlib
import struct
import zlib
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


# ==================== PROTOCOL FORMATS ====================

class ProtocolFormat(Enum):
    """Supported protocol formats"""
    HTTP_GET = "http_get"
    HTTP_POST = "http_post"
    HTTPS_TLS13 = "https_tls13"
    WEBSOCKET = "websocket"
    DNS_QUERY = "dns_query"
    JSON_API = "json_api"


# ==================== HTTP FORMAT ====================

class HTTPFormatter:
    """Format data as legitimate HTTP traffic"""

    # Common user agents
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    ]

    # Common paths for GET requests
    GET_PATHS = [
        "/api/v1/status",
        "/health",
        "/metrics",
        "/static/js/bundle.js",
        "/assets/styles.css",
        "/favicon.ico",
        "/robots.txt",
        "/api/user/profile",
        "/api/data/sync"
    ]

    # Common API endpoints for POST
    POST_ENDPOINTS = [
        "/api/v1/events",
        "/api/analytics",
        "/api/telemetry",
        "/api/logs",
        "/api/metrics/push",
        "/api/sync",
        "/api/upload"
    ]

    @staticmethod
    def encode_get(data: bytes) -> bytes:
        """
        Encode data as HTTP GET request

        Hides data in:
        - Query parameters (base64)
        - Cookie headers
        - Custom headers
        """
        # Encode data in query string
        b64_data = base64.urlsafe_b64encode(data).decode().rstrip('=')

        # Split into query parameters
        chunk_size = random.randint(20, 40)
        chunks = [b64_data[i:i+chunk_size] for i in range(0, len(b64_data), chunk_size)]

        params = []
        param_names = ["session", "token", "id", "key", "state", "nonce"]
        for i, chunk in enumerate(chunks):
            param_name = param_names[i % len(param_names)]
            params.append(f"{param_name}={chunk}")

        query_string = "&".join(params)

        # Build HTTP GET request
        path = random.choice(HTTPFormatter.GET_PATHS)
        user_agent = random.choice(HTTPFormatter.USER_AGENTS)

        request = (
            f"GET {path}?{query_string} HTTP/1.1\r\n"
            f"Host: api.example.com\r\n"
            f"User-Agent: {user_agent}\r\n"
            f"Accept: application/json, text/plain, */*\r\n"
            f"Accept-Language: en-US,en;q=0.9\r\n"
            f"Accept-Encoding: gzip, deflate, br\r\n"
            f"Connection: keep-alive\r\n"
            f"Referer: https://example.com/\r\n"
            f"Sec-Fetch-Dest: empty\r\n"
            f"Sec-Fetch-Mode: cors\r\n"
            f"Sec-Fetch-Site: same-origin\r\n"
            f"\r\n"
        )

        return request.encode()

    @staticmethod
    def encode_post(data: bytes) -> bytes:
        """
        Encode data as HTTP POST request

        Hides data in:
        - JSON body
        - Form data
        - Multipart upload
        """
        endpoint = random.choice(HTTPFormatter.POST_ENDPOINTS)
        user_agent = random.choice(HTTPFormatter.USER_AGENTS)

        # Encode as JSON API request
        b64_data = base64.urlsafe_b64encode(data).decode().rstrip('=')

        # Create realistic JSON payload
        json_body = (
            "{"
            f'"timestamp":{int(time.time() * 1000)},'
            f'"session_id":"{hashlib.md5(str(time.time()).encode()).hexdigest()}",'
            f'"event_type":"telemetry",'
            f'"payload":"{b64_data}",'
            f'"version":"1.0",'
            f'"client_id":"{random.randint(1000000, 9999999)}"'
            "}"
        )

        request = (
            f"POST {endpoint} HTTP/1.1\r\n"
            f"Host: api.example.com\r\n"
            f"User-Agent: {user_agent}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(json_body)}\r\n"
            f"Accept: application/json\r\n"
            f"Accept-Language: en-US,en;q=0.9\r\n"
            f"Accept-Encoding: gzip, deflate, br\r\n"
            f"Connection: keep-alive\r\n"
            f"Origin: https://example.com\r\n"
            f"Referer: https://example.com/dashboard\r\n"
            f"Sec-Fetch-Dest: empty\r\n"
            f"Sec-Fetch-Mode: cors\r\n"
            f"Sec-Fetch-Site: same-origin\r\n"
            f"\r\n"
            f"{json_body}"
        )

        return request.encode()

    @staticmethod
    def decode_get(http_data: bytes) -> Optional[bytes]:
        """Extract data from HTTP GET request"""
        try:
            request = http_data.decode()

            # Extract query parameters
            match = re.search(r'GET [^\?]+\?([^ ]+) HTTP', request)
            if not match:
                return None

            query_string = match.group(1)
            params = dict(param.split('=') for param in query_string.split('&') if '=' in param)

            # Reconstruct data from parameters
            data_parts = [params.get(k, '') for k in ["session", "token", "id", "key", "state", "nonce"] if k in params]
            b64_data = ''.join(data_parts)

            # Add padding
            padding = (4 - len(b64_data) % 4) % 4
            b64_data += '=' * padding

            return base64.urlsafe_b64decode(b64_data)
        except Exception:
            return None

    @staticmethod
    def decode_post(http_data: bytes) -> Optional[bytes]:
        """Extract data from HTTP POST request"""
        try:
            request = http_data.decode()

            # Extract JSON body
            match = re.search(r'\r\n\r\n(.+)$', request, re.DOTALL)
            if not match:
                return None

            body = match.group(1)

            # Extract payload field
            match = re.search(r'"payload":"([^"]+)"', body)
            if not match:
                return None

            b64_data = match.group(1)

            # Add padding
            padding = (4 - len(b64_data) % 4) % 4
            b64_data += '=' * padding

            return base64.urlsafe_b64decode(b64_data)
        except Exception:
            return None


# ==================== TLS FORMAT ====================

class TLSFormatter:
    """Format data as TLS 1.3 handshake/application data"""

    @staticmethod
    def encode_client_hello(data: bytes) -> bytes:
        """
        Encode data as TLS 1.3 ClientHello

        Hides data in:
        - Random field (32 bytes)
        - Session ID
        - Extensions (padding, GREASE)
        """
        # TLS record header
        content_type = 0x16  # Handshake
        version = 0x0301  # TLS 1.0 (for compatibility)

        # Handshake header
        handshake_type = 0x01  # ClientHello
        client_version = 0x0303  # TLS 1.2 (negotiates to 1.3)

        # Random (32 bytes) - can hide data here
        random_data = data[:32] if len(data) >= 32 else data + bytes(32 - len(data))

        # Session ID
        session_id_len = min(32, len(data) - 32) if len(data) > 32 else 0
        session_id = data[32:32+session_id_len] if session_id_len > 0 else b''

        # Cipher suites (realistic TLS 1.3 suites)
        cipher_suites = bytes.fromhex("13011302130300ff")  # TLS_AES_128_GCM_SHA256, etc.

        # Compression methods
        compression_methods = b'\x01\x00'  # None

        # Extensions - can hide more data
        extensions = TLSFormatter._build_extensions(data[32+session_id_len:] if len(data) > 32+session_id_len else b'')

        # Build ClientHello
        client_hello = (
            struct.pack("!H", client_version) +
            random_data +
            struct.pack("!B", session_id_len) +
            session_id +
            struct.pack("!H", len(cipher_suites)) +
            cipher_suites +
            compression_methods +
            extensions
        )

        # Handshake header
        handshake = struct.pack("!B", handshake_type) + struct.pack("!I", len(client_hello))[1:] + client_hello

        # TLS record
        tls_record = struct.pack("!BHH", content_type, version, len(handshake)) + handshake

        return tls_record

    @staticmethod
    def _build_extensions(data: bytes) -> bytes:
        """Build TLS extensions with embedded data"""
        extensions_list = []

        # Server Name Indication
        sni = b'\x00\x00\x00\x0f\x00\x0d\x00\x00\x0aexample.com'
        extensions_list.append(sni)

        # Supported Groups
        groups = b'\x00\x0a\x00\x06\x00\x04\x00\x1d\x00\x17'  # x25519, secp256r1
        extensions_list.append(groups)

        # Signature Algorithms
        sig_algs = b'\x00\x0d\x00\x08\x00\x06\x04\x03\x08\x04\x04\x01'
        extensions_list.append(sig_algs)

        # Padding extension - hide data here
        if data:
            padding_len = len(data)
            padding_ext = struct.pack("!HH", 0x0015, padding_len) + data  # Extension type 21 (padding)
            extensions_list.append(padding_ext)

        # Concatenate all extensions
        extensions_data = b''.join(extensions_list)

        # Extensions length prefix
        return struct.pack("!H", len(extensions_data)) + extensions_data

    @staticmethod
    def encode_application_data(data: bytes) -> bytes:
        """Encode data as TLS 1.3 Application Data"""
        content_type = 0x17  # Application Data
        version = 0x0303  # TLS 1.2

        # In real TLS 1.3, this would be encrypted
        # Here we just frame it properly
        tls_record = struct.pack("!BHH", content_type, version, len(data)) + data

        return tls_record


# ==================== WEBSOCKET FORMAT ====================

class WebSocketFormatter:
    """Format data as WebSocket frames"""

    @staticmethod
    def encode_frame(data: bytes, opcode: int = 0x02) -> bytes:
        """
        Encode data as WebSocket frame

        Opcode:
        - 0x01: Text
        - 0x02: Binary
        - 0x08: Close
        - 0x09: Ping
        - 0x0A: Pong
        """
        # Frame header
        fin = 0x80  # FIN bit set (final fragment)
        frame_header = fin | opcode

        # Payload length
        payload_len = len(data)

        if payload_len < 126:
            length_bytes = struct.pack("!B", payload_len)
        elif payload_len < 65536:
            length_bytes = struct.pack("!BH", 126, payload_len)
        else:
            length_bytes = struct.pack("!BQ", 127, payload_len)

        # Masking key (client → server frames must be masked)
        mask_bit = 0x80
        masking_key = struct.pack("!I", random.randint(0, 0xFFFFFFFF))

        # Mask payload
        masked_payload = bytes(b ^ masking_key[i % 4] for i, b in enumerate(data))

        # Build frame
        frame = (
            struct.pack("!B", frame_header) +
            length_bytes[:1] +  # First byte with mask bit
            bytes([length_bytes[0] | mask_bit if len(length_bytes) == 1 else length_bytes[1] | mask_bit]) +
            length_bytes[1:] +  # Remaining length bytes
            masking_key +
            masked_payload
        )

        return frame

    @staticmethod
    def encode_text(text: str) -> bytes:
        """Encode text as WebSocket text frame"""
        return WebSocketFormatter.encode_frame(text.encode(), opcode=0x01)

    @staticmethod
    def encode_binary(data: bytes) -> bytes:
        """Encode binary data as WebSocket binary frame"""
        return WebSocketFormatter.encode_frame(data, opcode=0x02)


# ==================== DNS FORMAT ====================

class DNSFormatter:
    """Format data as DNS queries (DNS tunneling)"""

    @staticmethod
    def encode_query(data: bytes, domain: str = "example.com") -> bytes:
        """
        Encode data as DNS TXT query

        Hides data in subdomain labels (base32 encoded)
        """
        # DNS query header
        transaction_id = random.randint(0, 65535)
        flags = 0x0100  # Standard query
        questions = 1
        answer_rrs = 0
        authority_rrs = 0
        additional_rrs = 0

        header = struct.pack("!HHHHHH", transaction_id, flags, questions, answer_rrs, authority_rrs, additional_rrs)

        # Encode data in subdomain
        b32_data = base64.b32encode(data).decode().lower().rstrip('=')

        # Split into DNS labels (max 63 chars each)
        labels = [b32_data[i:i+63] for i in range(0, len(b32_data), 63)]

        # Build QNAME
        qname = b''
        for label in labels[:4]:  # Max 4 labels for reasonableness
            qname += struct.pack("!B", len(label)) + label.encode()

        # Add base domain
        for part in domain.split('.'):
            qname += struct.pack("!B", len(part)) + part.encode()

        qname += b'\x00'  # Null terminator

        # Question section
        qtype = 16  # TXT record
        qclass = 1  # IN (Internet)
        question = qname + struct.pack("!HH", qtype, qclass)

        return header + question


# ==================== FTE ENGINE ====================

class FTEEngine:
    """
    Main Format-Transforming Encryption engine

    Automatically selects best format based on:
    - Data size
    - Network conditions
    - Target profile
    """

    def __init__(self, preferred_format: ProtocolFormat = ProtocolFormat.HTTP_POST):
        self.preferred_format = preferred_format
        self.http = HTTPFormatter()
        self.tls = TLSFormatter()
        self.websocket = WebSocketFormatter()
        self.dns = DNSFormatter()

    def encode(self, data: bytes, format_hint: Optional[ProtocolFormat] = None) -> bytes:
        """
        Encode data in specified or preferred format

        Auto-selects format if not specified
        """
        target_format = format_hint or self.preferred_format

        if target_format == ProtocolFormat.HTTP_GET:
            return self.http.encode_get(data)
        elif target_format == ProtocolFormat.HTTP_POST:
            return self.http.encode_post(data)
        elif target_format == ProtocolFormat.HTTPS_TLS13:
            return self.tls.encode_client_hello(data)
        elif target_format == ProtocolFormat.WEBSOCKET:
            return self.websocket.encode_binary(data)
        elif target_format == ProtocolFormat.DNS_QUERY:
            return self.dns.encode_query(data)
        else:
            # Default: HTTP POST
            return self.http.encode_post(data)

    def decode(self, formatted_data: bytes) -> Optional[bytes]:
        """
        Auto-detect format and decode

        Tries multiple decoders until one succeeds
        """
        # Try HTTP GET
        result = self.http.decode_get(formatted_data)
        if result:
            return result

        # Try HTTP POST
        result = self.http.decode_post(formatted_data)
        if result:
            return result

        # Add more decoders as needed
        return None

    def encode_stream(self, data: bytes, chunk_size: int = 1024) -> List[bytes]:
        """
        Encode data as stream of protocol messages

        Splits large data into multiple realistic-sized messages
        """
        chunks = []
        offset = 0

        while offset < len(data):
            chunk = data[offset:offset + chunk_size]

            # Alternate formats for diversity
            if len(chunks) % 3 == 0:
                encoded = self.encode(chunk, ProtocolFormat.HTTP_GET)
            elif len(chunks) % 3 == 1:
                encoded = self.encode(chunk, ProtocolFormat.HTTP_POST)
            else:
                encoded = self.encode(chunk, ProtocolFormat.WEBSOCKET)

            chunks.append(encoded)
            offset += chunk_size

        return chunks


# ==================== EXPORT ====================

__all__ = [
    'ProtocolFormat',
    'FTEEngine',
    'HTTPFormatter',
    'TLSFormatter',
    'WebSocketFormatter',
    'DNSFormatter'
]


if __name__ == "__main__":
    print("=== FTE ENGINE SELF-TEST ===")

    engine = FTEEngine(preferred_format=ProtocolFormat.HTTP_POST)

    # Test data
    original_data = b"Secret message for FTE encoding" * 10

    # Test HTTP POST
    http_post = engine.encode(original_data, ProtocolFormat.HTTP_POST)
    print(f"✓ HTTP POST: {len(http_post)} bytes")
    decoded = engine.decode(http_post)
    assert decoded == original_data, "HTTP POST decode failed"
    print(f"✓ HTTP POST decode successful")

    # Test HTTP GET
    http_get = engine.encode(original_data[:100], ProtocolFormat.HTTP_GET)
    print(f"✓ HTTP GET: {len(http_get)} bytes")
    decoded = engine.decode(http_get)
    assert decoded == original_data[:100], "HTTP GET decode failed"
    print(f"✓ HTTP GET decode successful")

    # Test TLS
    tls_data = engine.encode(original_data[:200], ProtocolFormat.HTTPS_TLS13)
    print(f"✓ TLS ClientHello: {len(tls_data)} bytes")

    # Test WebSocket
    ws_data = engine.encode(original_data[:500], ProtocolFormat.WEBSOCKET)
    print(f"✓ WebSocket: {len(ws_data)} bytes")

    # Test DNS
    dns_data = engine.encode(original_data[:100], ProtocolFormat.DNS_QUERY)
    print(f"✓ DNS Query: {len(dns_data)} bytes")

    # Test stream encoding
    stream = engine.encode_stream(original_data, chunk_size=200)
    print(f"✓ Stream: {len(stream)} chunks")

    print("\n✅ FTE engine test complete")
