"""Bounded persisted pitch windows. Peer fingerprints are not user identity."""

from datetime import datetime, timezone
from hashlib import sha256
import re

WINDOW_US = 60_000_000
REQUEST_LIMIT = 10
MAX_PEERS = 128


def consume(state: dict, peer: str, now: datetime, *, limit: int = REQUEST_LIMIT) -> tuple[dict, int]:
    """Return new state and retry seconds (zero admits). Never mutate input."""
    if type(limit) is not int or not 1 <= limit <= 120: raise ValueError("Invalid admission limit.")
    if not isinstance(peer, str) or not peer or len(peer) > 256 or now.tzinfo is None:
        raise ValueError("Invalid pitch admission source or clock.")
    last = state.get("last_seen_us")
    peers = state.get("peers")
    if type(last) is not int or last < 0 or not isinstance(peers, dict) or len(peers) > MAX_PEERS:
        raise ValueError("Invalid persisted pitch admission state.")
    for key, times in peers.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key)
                or not isinstance(times, list) or not 1 <= len(times) <= limit
                or any(type(value) is not int or not 0 <= value <= last for value in times)
                or times != sorted(times)):
            raise ValueError("Invalid persisted pitch admission window.")
    delta = now - datetime(1970, 1, 1, tzinfo=timezone.utc)
    wall_us = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    if wall_us < 0:
        raise ValueError("Invalid pitch admission clock.")
    effective = max(wall_us, last)  # A restart or backward clock jump cannot reset the window.
    active = {key: [value for value in times if value > effective - WINDOW_US] for key, times in peers.items()}
    active = {key: times for key, times in active.items() if times}
    key = sha256(peer.encode("utf-8")).hexdigest()
    times = active.get(key, [])
    retry_until = None
    if len(times) >= limit:
        retry_until = times[0] + WINDOW_US
    elif key not in active and len(active) >= MAX_PEERS:
        # Capacity becomes free only when an entire peer window expires.
        retry_until = min(values[-1] + WINDOW_US for values in active.values())
    else:
        active[key] = times + [effective]
    retry = max(1, (retry_until - wall_us + 999_999) // 1_000_000) if retry_until is not None else 0
    return {"last_seen_us": effective, "peers": active}, retry
