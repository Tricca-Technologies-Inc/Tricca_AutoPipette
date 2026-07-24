"""Long-running control daemon (``tapd``) for Tricca AutoPipette.

Owns the single persistent connection to Moonraker and exposes a local
control-plane WebSocket that other processes (the kiosk, the interactive
``tap`` CLI) talk to instead of each opening their own Moonraker connection.
"""

from __future__ import annotations
