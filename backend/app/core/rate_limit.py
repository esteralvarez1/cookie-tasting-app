from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory rate limiter keyed by client IP.
# Limits are per-process and reset on restart. For multi-process or multi-node
# deployments, replace the default storage with a Redis backend:
#   from slowapi import Limiter
#   limiter = Limiter(key_func=get_remote_address, storage_uri="redis://localhost:6379")
limiter = Limiter(key_func=get_remote_address, default_limits=[])
