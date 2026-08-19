import hashlib
import json
import math
import time


def build_payload(query: str) -> str:
    return json.dumps(
        {"query": query},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_timestamp(now: float | None = None) -> int:
    return math.ceil(time.time() if now is None else now)


def build_signature(
    app_id: str,
    timestamp: int,
    payload: str,
    secret: str,
) -> str:
    factor = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(factor.encode("utf-8")).hexdigest()


def build_authorization_header(
    app_id: str,
    timestamp: int,
    signature: str,
) -> str:
    return (
        f"SHA256 Credential={app_id}, "
        f"Timestamp={timestamp}, "
        f"Signature={signature}"
    )
