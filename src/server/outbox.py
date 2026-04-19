"""
Server-side outbox for reliable server→agent CMD / CFG.

Mirrors the agent's outbox pattern (agent/outbox.py) but server-side:
  - Every CMD / CFG gets a monotonic seq and is held as a PendingCmd
    until the agent sends `ACK|<agent_id>|<seq>|ok`.
  - A background tick retries unacked messages with exponential
    backoff, bounded by MAX_RETRIES and MAX_DELAY_S.
  - Unlike the agent outbox, not persisted: a server restart wipes
    the in-flight CMD set. Operators can re-issue from the dashboard
    if something was racing a restart.

Scope deliberately narrow: only CMD / CFG go through here. DET / STAT /
LOG are *agent-originated* and already handled by the agent's outbox;
the server just ACKs them. APPROVE / ACK don't need reliability (APPROVE
is resent on every HELLO from an approved agent via 6039484).

Broadcast targets ("*") are sent once and NOT tracked — there's no
single agent to expect an ACK from.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from comms import protocol as P


# Base delay tuned to the Meshtastic agent's drain rate (~6 s/send).
# Retrying any faster would just pile duplicates into airtime that a
# busy DET stream might already be competing for.
DEFAULT_BASE_DELAY_S = 6.0
DEFAULT_MAX_DELAY_S = 120.0
DEFAULT_MAX_RETRIES = 5


@dataclass
class PendingCmd:
    agent_id: str
    seq: int
    wire: str
    verb: str
    enqueued_at: float
    last_try_at: float
    retries: int = 0
    acked: bool = False


class ServerOutbox:
    """Per-server outbox keyed by (agent_id, seq).

    Thread-safe: `send_fn` is called with the lock released so a
    blocking mesh `link.send(...)` can't stall `on_ack` or `tick`.
    """

    def __init__(
        self,
        send_fn: Callable[[str], None],
        base_delay_s: float = DEFAULT_BASE_DELAY_S,
        max_delay_s: float = DEFAULT_MAX_DELAY_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self._send = send_fn
        self.base_delay_s = base_delay_s
        self.max_delay_s = max_delay_s
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._next_seq = 1
        self._pending: Dict[Tuple[str, int], PendingCmd] = {}
        # Stop event used by the optional background ticker.
        self._stop = threading.Event()
        self._ticker: Optional[threading.Thread] = None

    # -- allocation ------------------------------------------------------

    def _alloc_seq(self) -> int:
        with self._lock:
            s = self._next_seq
            self._next_seq += 1
            return s

    # -- send ------------------------------------------------------------

    def send_cmd(self, agent_id: str, verb: str, args) -> int:
        """Enqueue + send a CMD. Returns the allocated seq.

        Broadcast targets ("*") are sent once and not tracked — there's
        no single ACK to wait for.
        """
        seq = self._alloc_seq()
        wire = P.encode_cmd(agent_id, seq, verb, list(args or []))
        self._enqueue_and_send(agent_id, seq, wire, verb)
        return seq

    def send_cfg(self, agent_id: str, key: str, value: str) -> int:
        seq = self._alloc_seq()
        wire = P.encode_cfg(agent_id, seq, key, value)
        self._enqueue_and_send(agent_id, seq, wire, f"CFG:{key}")
        return seq

    def _enqueue_and_send(self, agent_id: str, seq: int, wire: str, verb: str) -> None:
        now = time.time()
        # Broadcast: fire-and-forget (no tracking). Swallow exceptions
        # so the caller (dashboard) gets a clean return.
        if agent_id == "*":
            try:
                self._send(wire)
            except Exception:
                pass
            return
        entry = PendingCmd(
            agent_id=agent_id, seq=seq, wire=wire, verb=verb,
            enqueued_at=now, last_try_at=now,
        )
        with self._lock:
            self._pending[(agent_id, seq)] = entry
        # First attempt outside the lock so a blocking link can't
        # stall ACKs arriving concurrently. A failed first send stays
        # in pending — the next tick will retry.
        try:
            self._send(wire)
        except Exception:
            pass

    # -- ack handling ----------------------------------------------------

    def on_ack(self, agent_id: str, seq: int) -> bool:
        """Mark a pending CMD as acked. Returns True if it matched one
        we were actually tracking (False on duplicate ACK or unrelated
        DET/STAT ACK that happens to share a seq)."""
        with self._lock:
            removed = self._pending.pop((agent_id, seq), None)
        return removed is not None

    # -- introspection ---------------------------------------------------

    def pending(self, agent_id: Optional[str] = None) -> List[PendingCmd]:
        """Snapshot of unacked CMDs, optionally filtered to one agent."""
        with self._lock:
            items = list(self._pending.values())
        if agent_id is None:
            return items
        return [p for p in items if p.agent_id == agent_id]

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    # -- retries ---------------------------------------------------------

    def tick(self, now: Optional[float] = None) -> int:
        """Retry stale pendings. Returns how many were retried.

        Exponential backoff: delay = min(base * 2**retries, max_delay).
        A pending that blows past `max_retries` is dropped — operator
        can see the CMD is stuck via the comms log / outbox introspection
        and reissue from the dashboard."""
        if now is None:
            now = time.time()
        to_retry: List[str] = []
        with self._lock:
            for key, pc in list(self._pending.items()):
                delay = min(self.base_delay_s * (2 ** pc.retries), self.max_delay_s)
                if (now - pc.last_try_at) < delay:
                    continue
                if pc.retries >= self.max_retries:
                    # Give up — drop so we don't queue forever.
                    del self._pending[key]
                    continue
                pc.retries += 1
                pc.last_try_at = now
                to_retry.append(pc.wire)
        for wire in to_retry:
            try:
                self._send(wire)
            except Exception:
                # A single send blip shouldn't abort the tick — the next
                # tick will pick it up.
                pass
        return len(to_retry)

    # -- optional background ticker -------------------------------------

    def start_ticker(self, interval_s: float = 3.0) -> None:
        """Start a daemon thread that calls `tick` every `interval_s`."""
        if self._ticker and self._ticker.is_alive():
            return
        self._stop.clear()
        self._ticker = threading.Thread(target=self._ticker_loop,
                                        args=(interval_s,), daemon=True)
        self._ticker.start()

    def stop_ticker(self) -> None:
        self._stop.set()
        if self._ticker:
            self._ticker.join(timeout=2.0)

    def _ticker_loop(self, interval_s: float) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                pass
            self._stop.wait(interval_s)
