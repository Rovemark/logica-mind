import base64
import hashlib
import hmac
from types import SimpleNamespace

from logica_mind.banco.servico import usuario_de
from logica_mind.web.server import make_handler


def _token(secret, owner, now):
    encoded = base64.urlsafe_b64encode(owner.encode()).rstrip(b"=").decode()
    bucket = int(now // 60)
    message = f"life-banco-v1:{encoded}:{bucket}".encode()
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), message, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"life-v1.{encoded}.{bucket}.{signature}"


def test_life_delegated_token_materializes_owner(monkeypatch):
    secret = "segredo-local-forte"
    now = 1_800_000_000
    monkeypatch.setattr("logica_mind.banco.servico.time.time", lambda: now)
    token = _token(secret, "owner-alice", now)
    assert usuario_de(f"Bearer {token}", secret) == "owner-alice"


def test_delegated_token_rejects_tampering_and_expiry(monkeypatch):
    secret = "segredo-local-forte"
    now = 1_800_000_000
    monkeypatch.setattr("logica_mind.banco.servico.time.time", lambda: now)
    token = _token(secret, "owner-alice", now)
    assert usuario_de(f"Bearer {token[:-1]}x", secret) is None
    assert usuario_de(f"Bearer {_token(secret, 'owner-alice', now - 180)}", secret) is None


def test_global_token_uses_company_tenant_owner(monkeypatch):
    secret = "segredo-local-forte"
    monkeypatch.setenv("LOGICAOS_OWNER_ID", "empresa-markus")
    assert usuario_de(f"Bearer {secret}", secret) == "empresa-markus"
    assert usuario_de("Bearer invalido", secret) is None


def test_global_token_keeps_legacy_fallback_without_company_config(monkeypatch):
    secret = "segredo-local-forte"
    monkeypatch.delenv("LOGICAOS_OWNER_ID", raising=False)
    assert usuario_de(f"Bearer {secret}", secret) == "dono"


def test_http_post_lets_banco_validate_delegated_owner_token():
    """O portão HTTP genérico não conhece life-v1; o Banco conhece e deve recebê-lo."""
    Handler = make_handler(SimpleNamespace(), allow_writes=True, token="segredo-global")
    pedido = object.__new__(Handler)
    pedido.path = "/api/banco/comentario.criar"
    pedido.command = "POST"
    pedido._t0 = None
    pedido._can_write = lambda: False  # life-v1 falha aqui por desenho
    pedido._body = lambda: {"no_id": "n1", "corpo": "olá"}
    chamadas = []
    pedido._banco = lambda metodo, path, qs, body: chamadas.append((metodo, path, body)) or "ok"
    pedido._json = lambda corpo, codigo=200: (codigo, corpo)

    assert pedido.do_POST() == "ok"
    assert chamadas == [("POST", "/api/banco/comentario.criar", {"no_id": "n1", "corpo": "olá"})]
