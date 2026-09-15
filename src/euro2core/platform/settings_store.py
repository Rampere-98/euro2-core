"""Server configuration edited from the app (Ajustes → Administración), so nobody has to
open a file on the server. Values live in `app_setting`; secrets are Fernet-encrypted with a
key derived from SECRET_KEY. `.env` remains the base layer; the store overrides it."""

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import AppSetting


@dataclass(frozen=True)
class Spec:
    key: str
    default: Any
    secret: bool = False
    kind: str = "str"  # str | int | float | bool | json
    label_es: str = ""
    help_es: str = ""


SPECS: tuple[Spec, ...] = (
    Spec("numista_api_key", "", True, label_es="Numista API key"),
    Spec("ebay_client_id", "", True, label_es="eBay Client ID"),
    Spec("ebay_client_secret", "", True, label_es="eBay Client Secret"),
    Spec("duckdns_domain", "", False, label_es="Dominio DuckDNS", help_es="p. ej. euro2"),
    Spec("duckdns_token", "", True, label_es="Token DuckDNS"),
    Spec(
        "public_origins",
        "",
        False,
        label_es="Orígenes permitidos (CORS)",
        help_es="Separados por comas; vacío = cualquiera",
    ),
    Spec("user_agent", "euro2-core/0.1", False, label_es="User-Agent de los rastreadores"),
    Spec("deal_threshold_pct", 15.0, False, "float", label_es="Umbral de chollo (%)"),
    Spec("registration_open", True, False, "bool", label_es="Registro abierto"),
    Spec(
        "replica_words",
        [],
        False,
        "json",
        label_es="Palabras extra de réplica/fantasía",
        help_es="Se suman a la lista integrada",
    ),
    Spec(
        "altered_words",
        [],
        False,
        "json",
        label_es="Palabras extra de moneda alterada",
        help_es="Se suman a la lista integrada",
    ),
    Spec(
        "mintage_buckets",
        [],
        False,
        "json",
        label_es="Tramos del modelo por tirada",
        help_es="[[tirada_max, bajo, alto], …]; vacío = valores por defecto",
    ),
)
SPEC_BY_KEY = {s.key: s for s in SPECS}


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encode(spec: Spec, value: Any) -> str:
    if spec.kind == "json":
        return json.dumps(value)
    if spec.kind == "bool":
        return "true" if value else "false"
    return str(value)


def _decode(spec: Spec, raw: str) -> Any:
    if spec.kind == "json":
        return json.loads(raw)
    if spec.kind == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if spec.kind == "int":
        return int(raw)
    if spec.kind == "float":
        return float(raw)
    return raw


def mask(value: str) -> str:
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 4 else "••••"


class SettingsStore:
    def __init__(self, session: AsyncSession, secret_key: str) -> None:
        self.session = session
        self.fernet = _fernet(secret_key)

    async def _rows(self) -> dict[str, AppSetting]:
        return {r.key: r for r in (await self.session.scalars(select(AppSetting))).all()}

    async def get(self, key: str, env_default: Any = None) -> Any:
        spec = SPEC_BY_KEY[key]
        row = await self.session.get(AppSetting, key)
        if row is None:
            return env_default if env_default not in (None, "") else spec.default
        raw = row.value
        if row.is_secret:
            try:
                raw = self.fernet.decrypt(raw.encode()).decode()
            except InvalidToken:  # SECRET_KEY changed: the stored secret is unreadable
                return env_default if env_default not in (None, "") else spec.default
        return _decode(spec, raw)

    async def set(self, key: str, value: Any) -> None:
        spec = SPEC_BY_KEY[key]
        raw = _encode(spec, value)
        if spec.secret:
            raw = self.fernet.encrypt(raw.encode()).decode()
        row = await self.session.get(AppSetting, key)
        if row is None:
            self.session.add(AppSetting(key=key, value=raw, is_secret=spec.secret))
        else:
            row.value = raw
            row.is_secret = spec.secret
        await self.session.flush()

    async def delete(self, key: str) -> None:
        row = await self.session.get(AppSetting, key)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    async def view(self, env: dict[str, Any]) -> list[dict[str, Any]]:
        """Everything the admin panel shows: secrets masked, source of each value."""
        rows = await self._rows()
        out = []
        for spec in SPECS:
            env_value = env.get(spec.key)
            value = await self.get(spec.key, env_value)
            stored = spec.key in rows
            source = "app" if stored else ("env" if env_value not in (None, "") else "default")
            shown = mask(str(value)) if spec.secret else value
            out.append(
                {
                    "key": spec.key,
                    "label": spec.label_es,
                    "help": spec.help_es,
                    "kind": spec.kind,
                    "secret": spec.secret,
                    "value": shown,
                    "source": source,
                    "set": bool(value) if spec.secret else True,
                }
            )
        return out
