"""
Segurança da API: autenticação, rate limit, proteção contra força bruta, headers e CORS.

Tudo é configurado por variáveis de ambiente (ver `.env.example`) e não exige dependências extras.

Modos de autenticação (podem coexistir):
- API key:    `X-API-Key: <chave>` ou `Authorization: Bearer <chave>` (integrações / scripts).
- Basic Auth: `BASIC_AUTH_USER` + `BASIC_AUTH_PASSWORD` (o navegador pede a senha uma única vez e a
              reutiliza no dashboard e nas chamadas `fetch` do mesmo domínio).

Política "fail closed": com `APP_ENV=production`, a aplicação se recusa a iniciar sem credenciais, a
menos que `ALLOW_PUBLIC=true` seja definido de forma explícita (acesso público, protegido só por rate limit).
"""
import base64
import logging
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("scout.security")

MIN_SECRET_LENGTH = 16
EXEMPT_PATHS = {"/health"}
RATE_LIMIT_EXEMPT_PREFIXES = ("/static/",)
MAX_FAILED_AUTH_PER_MINUTE = 10
DEV_DEFAULT_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _env_csv(name: str) -> Tuple[str, ...]:
    return tuple(p.strip().rstrip("/") for p in os.getenv(name, "").split(",") if p.strip())


@dataclass(frozen=True)
class SecuritySettings:
    env: str = "development"
    api_key: str = ""
    basic_user: str = ""
    basic_password: str = ""
    allow_public: bool = False
    allowed_origins: Tuple[str, ...] = ()
    rate_limit_per_min: int = 300
    docs_enabled: bool = True
    trust_proxy: bool = False

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def basic_configured(self) -> bool:
        return bool(self.basic_user and self.basic_password)

    @property
    def auth_enforced(self) -> bool:
        return bool(self.api_key) or self.basic_configured

    def validate(self) -> None:
        """Falha cedo (na inicialização) em configurações inseguras ou inconsistentes."""
        if bool(self.basic_user) != bool(self.basic_password):
            raise RuntimeError("Defina BASIC_AUTH_USER e BASIC_AUTH_PASSWORD juntos (ou nenhum dos dois).")
        if self.is_production:
            if not self.auth_enforced and not self.allow_public:
                raise RuntimeError(
                    "APP_ENV=production exige autenticação: defina API_KEY e/ou BASIC_AUTH_USER/BASIC_AUTH_PASSWORD, "
                    "ou ALLOW_PUBLIC=true para publicar sem login (apenas com rate limit)."
                )
            for label, secret in (("API_KEY", self.api_key), ("BASIC_AUTH_PASSWORD", self.basic_password)):
                if secret and len(secret) < MIN_SECRET_LENGTH:
                    raise RuntimeError(f"{label} muito curta: use ao menos {MIN_SECRET_LENGTH} caracteres em produção.")
        elif not self.auth_enforced:
            logger.warning("API sem autenticação (modo desenvolvimento). Não exponha esta instância na internet.")


def load_security_settings() -> SecuritySettings:
    env = os.getenv("APP_ENV", "development").strip().lower()
    production = env == "production"
    origins = _env_csv("ALLOWED_ORIGINS") or (() if production else DEV_DEFAULT_ORIGINS)
    return SecuritySettings(
        env=env,
        api_key=os.getenv("API_KEY", "").strip(),
        basic_user=os.getenv("BASIC_AUTH_USER", "").strip(),
        basic_password=os.getenv("BASIC_AUTH_PASSWORD", "").strip(),
        allow_public=_env_bool("ALLOW_PUBLIC", False),
        allowed_origins=origins,
        rate_limit_per_min=_env_int("RATE_LIMIT_PER_MIN", 300),
        docs_enabled=_env_bool("DOCS_ENABLED", not production),
        trust_proxy=_env_bool("TRUST_PROXY", False),
    )


class SlidingWindowLimiter:
    """Limitador de janela deslizante em memória (por processo). Thread-safe."""

    def __init__(self, limit: int, window_s: float = 60.0):
        self.limit = limit
        self.window_s = window_s
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, q: Deque[float], now: float) -> None:
        while q and now - q[0] >= self.window_s:
            q.popleft()

    def retry_after(self, key: str) -> float:
        """Segundos até liberar a chave, ou 0 se não estiver bloqueada (não registra acesso)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 0.0
            self._prune(q, now)
            return max(0.0, self.window_s - (now - q[0])) if len(q) >= self.limit else 0.0

    def hit(self, key: str) -> Tuple[bool, float]:
        """Registra um acesso. Retorna (permitido, retry_after_s)."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 10_000:  # evita crescimento ilimitado
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window_s]:
                    del self._hits[k]
            q = self._hits.setdefault(key, deque())
            self._prune(q, now)
            if len(q) >= self.limit:
                return False, max(0.0, self.window_s - (now - q[0]))
            q.append(now)
            return True, 0.0

    def record(self, key: str) -> None:
        """Registra uma ocorrência sem verificar o limite (usado para falhas de autenticação)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            self._prune(q, now)
            q.append(now)


class SecurityMiddleware:
    """Middleware ASGI: autenticação, rate limit, bloqueio de força bruta e headers de segurança."""

    def __init__(self, app: ASGIApp, settings: SecuritySettings):
        self.app = app
        self.s = settings
        self.rate = SlidingWindowLimiter(settings.rate_limit_per_min) if settings.rate_limit_per_min > 0 else None
        self.failures = SlidingWindowLimiter(MAX_FAILED_AUTH_PER_MINUTE)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _headers(scope: Scope) -> Dict[str, str]:
        return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}

    def _client_ip(self, scope: Scope, headers: Dict[str, str]) -> str:
        if self.s.trust_proxy:
            fwd = headers.get("x-forwarded-for", "")
            if fwd:  # proxy confiável acrescenta o IP real ao final da lista
                return fwd.split(",")[-1].strip()
        client = scope.get("client")
        return client[0] if client else "unknown"

    def _authorized(self, headers: Dict[str, str]) -> bool:
        if not self.s.auth_enforced:
            return True
        if self.s.api_key:
            candidate = headers.get("x-api-key", "")
            if candidate and secrets.compare_digest(candidate.encode(), self.s.api_key.encode()):
                return True
        auth = headers.get("authorization", "")
        scheme, _, value = auth.partition(" ")
        value = value.strip()
        if scheme.lower() == "bearer" and self.s.api_key and value:
            if secrets.compare_digest(value.encode(), self.s.api_key.encode()):
                return True
        if scheme.lower() == "basic" and self.s.basic_configured and value:
            try:
                user, _, pwd = base64.b64decode(value).decode("utf-8").partition(":")
            except Exception:
                return False
            ok_user = secrets.compare_digest(user.encode(), self.s.basic_user.encode())
            ok_pwd = secrets.compare_digest(pwd.encode(), self.s.basic_password.encode())
            return ok_user and ok_pwd
        return False

    def _security_headers(self, headers: Dict[str, str]) -> List[Tuple[bytes, bytes]]:
        out = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        ]
        if self.s.is_production and headers.get("x-forwarded-proto", "").lower() == "https":
            out.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
        return out

    # --------------------------------------------------------------------- ASGI
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = self._headers(scope)
        extra = self._security_headers(headers)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + extra
            await send(message)

        path = scope.get("path", "")
        if path in EXEMPT_PATHS:
            await self.app(scope, receive, send_with_headers)
            return

        ip = self._client_ip(scope, headers)

        # 1) Bloqueio de força bruta: IPs com muitas falhas recentes de autenticação.
        wait = self.failures.retry_after(ip)
        if wait > 0:
            await self._reject(429, "Muitas tentativas de autenticação. Aguarde e tente novamente.", wait, scope, receive, send_with_headers)
            return

        # 2) Rate limit geral (assets estáticos ficam de fora: uma página carrega vários arquivos).
        if self.rate and not path.startswith(RATE_LIMIT_EXEMPT_PREFIXES):
            allowed, wait = self.rate.hit(ip)
            if not allowed:
                await self._reject(429, "Limite de requisições excedido.", wait, scope, receive, send_with_headers)
                return

        # 3) Autenticação. Só conta como tentativa de força bruta quando credenciais foram APRESENTADAS e
        #    estavam erradas: o navegador sempre faz uma 1ª requisição sem credenciais (desafio 401) antes de
        #    reenviar com Basic Auth, e isso não pode bloquear um usuário legítimo.
        if not self._authorized(headers):
            if headers.get("authorization") or headers.get("x-api-key"):
                self.failures.record(ip)
            await self._reject(401, "Autenticação necessária.", 0, scope, receive, send_with_headers, challenge=True)
            return

        await self.app(scope, receive, send_with_headers)

    @staticmethod
    async def _reject(status: int, detail: str, retry_after: float, scope: Scope, receive: Receive, send: Send,
                      challenge: bool = False) -> None:
        extra_headers: Dict[str, str] = {}
        if status == 429:
            extra_headers["Retry-After"] = str(max(1, int(retry_after + 0.999)))
        if challenge:
            extra_headers["WWW-Authenticate"] = 'Basic realm="Scout Data Intelligence", charset="UTF-8"'
        await JSONResponse({"detail": detail}, status_code=status, headers=extra_headers)(scope, receive, send)


def install_security(app: FastAPI, settings: Optional[SecuritySettings] = None) -> SecuritySettings:
    """Instala segurança e CORS no app. O CORS é adicionado por último para ficar mais externo:
    assim ele responde preflights (OPTIONS) antes da autenticação e decora também os 401/429."""
    settings = settings or load_security_settings()
    settings.validate()
    app.add_middleware(SecurityMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )
    return settings
