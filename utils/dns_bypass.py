"""
DNS-over-HTTPS bypass for ISP-blocked APIs.

Problem: Some Indian ISPs block DNS resolution for api.groq.com,
api.elevenlabs.io etc. VPNs get detected by ElevenLabs.

Solution: Resolve hostnames via Google's DNS-over-HTTPS (8.8.8.8)
directly inside Python — invisible to ISP and to the API provider.
"""
import socket
import requests

_original_getaddrinfo = socket.getaddrinfo
_dns_cache = {}

# Hostnames that need DNS bypass
BYPASS_HOSTS = {
    "api.groq.com",
    "api.elevenlabs.io",
    "api.cerebras.ai",
    "generativelanguage.googleapis.com",
    "openrouter.ai",
    "api.sambanova.ai",
}


def _resolve_via_doh(hostname: str) -> str:
    """Resolve hostname via Google DNS-over-HTTPS."""
    if hostname in _dns_cache:
        return _dns_cache[hostname]
    try:
        r = requests.get(
            "https://dns.google/resolve",
            params={"name": hostname, "type": "A"},
            timeout=5,
        )
        data = r.json()
        for answer in data.get("Answer", []):
            if answer.get("type") == 1:  # A record
                ip = answer["data"]
                _dns_cache[hostname] = ip
                return ip
    except Exception:
        pass
    return None


def _patched_getaddrinfo(host, port, *args, **kwargs):
    """Drop-in replacement for socket.getaddrinfo that uses DoH for blocked hosts."""
    if isinstance(host, str) and host in BYPASS_HOSTS:
        ip = _resolve_via_doh(host)
        if ip:
            return _original_getaddrinfo(ip, port, *args, **kwargs)
    return _original_getaddrinfo(host, port, *args, **kwargs)


def install():
    """Monkey-patch socket.getaddrinfo to use DNS-over-HTTPS for blocked hosts."""
    socket.getaddrinfo = _patched_getaddrinfo


# Auto-install on import
install()
