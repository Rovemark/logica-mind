"""Read-only, short-lived authority issued by the authenticated LogicaOS gateway.

A global Mind service token or loopback is not a human administrator. The gateway
signs the exact GET target with its service key after checking the human session.
The same read may be repeated within 90 seconds; it grants no write authority and
cannot be moved to another URL, owner, method or role.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time

SYSTEM_TABLES = frozenset((
    "agents", "squads", "chains", "agent_state", "agent_heartbeats", "tasks",
    "agent_messages", "organism_signals", "mind_logs", "ceo_approvals",
    "team_channels", "team_messages", "team_logs", "world_model",
    "chain_executions", "workflow_executions", "run_history", "workflows", "skill_usage",
))
# These tables must never fall back to a global view if provisioning is incomplete.
OWNER_TABLES = frozenset(("tasks", "agent_messages", "organism_signals", "mind_logs",
                          "ceo_approvals", "team_channels", "team_messages", "team_logs"))
_SECRET_COLUMN = re.compile(r"(?:password|passwd|secret|credential|private_key|api_key|key_b64|(?:^|_)token(?:_|$))", re.I)
_B64 = re.compile(r"^[A-Za-z0-9_-]+$")


def safe_columns(columns) -> bool:
    return bool(columns) and not any(_SECRET_COLUMN.search(str(column)) for column in columns)


def authorized(capability: str, secret: str, method: str, target: str, owner: str,
               authorization: str, loopback: bool, now_ms=None) -> bool:
    """Fail closed without a valid service bearer AND the gateway's signed claim."""
    return _authorized(capability, secret, method, target, owner, authorization, loopback,
                       now_ms, "system-inspection", "lsi-v1", "GET", "/api/banco/")


def seed_authorized(capability: str, secret: str, method: str, target: str, owner: str,
                    authorization: str, loopback: bool, body: bytes, now_ms=None) -> bool:
    """A different HMAC domain, exact POST target and exact bytes for identity override."""
    return _authorized(capability, secret, method, target, owner, authorization, loopback,
                       now_ms, "identity-seed", "lis-v1", "POST", "/api/self-model", body)


def _authorized(capability, secret, method, target, owner, authorization, loopback,
                now_ms, domain, version, expected_method, path_prefix, body=None):
    if not loopback or not secret or method != expected_method or not isinstance(capability, str):
        return False
    if not isinstance(authorization, str) or not hmac.compare_digest(authorization.encode(), f"Bearer {secret}".encode()):
        return False
    if not isinstance(target, str) or not target.startswith(path_prefix) or len(target) > 4096:
        return False
    if len(capability) > 8192:
        return False
    parts = capability.split(".")
    if len(parts) != 3 or parts[0] != version or not all(_B64.fullmatch(p) for p in parts[1:]):
        return False
    payload, signature = parts[1:]
    expected = base64.urlsafe_b64encode(hmac.new(secret.encode(),
        f"logicaos-{domain}-v1:{payload}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claim = json.loads(raw)
        issued = claim.get("issuedAt")
        actor = claim.get("actorId")
        now = time.time() * 1000 if now_ms is None else now_ms
        return (isinstance(claim, dict) and isinstance(issued, int) and not isinstance(issued, bool)
                and 0 <= now - issued <= 90_000
                and isinstance(actor, str) and bool(actor.strip()) and len(actor) <= 256
                and claim.get("ownerId") == owner and bool(owner)
                and claim.get("role") in ("super-admin", "tenant-admin")
                and claim.get("method") == method and claim.get("target") == target
                and (body is None or (isinstance(body, bytes)
                     and claim.get("bodyHash") == hashlib.sha256(body).hexdigest())))
    except (ValueError, TypeError, AttributeError, UnicodeError):
        return False
