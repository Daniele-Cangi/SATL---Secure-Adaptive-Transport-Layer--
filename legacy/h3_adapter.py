# ===================================
# h3_adapter.py  (NUOVO) — HTTP/3
# ===================================
from typing import Optional
import asyncio, ssl, urllib.parse
try:
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.connection import QuicConnection
    from aioquic.quic.events import HandshakeCompleted, ProtocolNegotiated, StreamDataReceived, ConnectionTerminated
    from aioquic.h3.connection import H3_ALPN, H3Connection
    from aioquic.h3.events import HeadersReceived, DataReceived, H3Event
    _HAS_H3=True
except Exception:
    _HAS_H3=False

class H3Sender:
    def __init__(self, url:str):
        self.url = url
        self._parsed = urllib.parse.urlparse(url)
        assert self._parsed.scheme in ("https","http3")
    async def send(self, payload: bytes)->bool:
        if not _HAS_H3: return False
        host = self._parsed.hostname; port = self._parsed.port or 443
        conf = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
        sslctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        reader, writer = await asyncio.open_connection(host, port, ssl=sslctx, server_hostname=host)
        # aioquic gestisce handshake internamente tramite Datagram; per brevità usiamo httpx-h3 fallback se non disponibile
        writer.close()
        return False  # Minimal stub: molte installazioni non hanno UDP permesso; lasciamo fallback