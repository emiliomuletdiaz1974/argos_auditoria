"""Lectura de secretos por una única interfaz (ARG-009). Nunca se registran valores."""

import json
from pathlib import Path
from typing import Protocol

import hvac
from cryptography.fernet import Fernet, InvalidToken
from hvac.exceptions import Forbidden, InvalidPath

from .errors import IntegridadError, SecretoNoAccesibleError


class AlmacenSecretos(Protocol):
    def leer(self, ruta: str) -> dict[str, str]: ...


class AlmacenVault:
    """kv-v2 de Vault; cada token solo ve las rutas que su política permite."""

    def __init__(self, url: str, token: str, montaje: str = "argos") -> None:
        self._cliente = hvac.Client(url=url, token=token)
        self._montaje = montaje

    def leer(self, ruta: str) -> dict[str, str]:
        try:
            respuesta = self._cliente.secrets.kv.v2.read_secret_version(
                path=ruta, mount_point=self._montaje, raise_on_deleted_version=True
            )
        except (Forbidden, InvalidPath):
            raise SecretoNoAccesibleError("secreto no accesible", detalles={"ruta": ruta}) from None
        datos = respuesta["data"]["data"]
        return {str(k): str(v) for k, v in datos.items()}


class AlmacenFicheroCifrado:
    """Solo para desarrollo sin Vault: un fichero Fernet con {ruta: {clave: valor}}."""

    def __init__(self, ruta: Path, clave: bytes) -> None:
        self._ruta = ruta
        self._fernet = Fernet(clave)

    @staticmethod
    def crear_clave() -> bytes:
        return Fernet.generate_key()

    def _cargar(self) -> dict[str, dict[str, str]]:
        if not self._ruta.exists():
            return {}
        try:
            descifrado = self._fernet.decrypt(self._ruta.read_bytes())
        except InvalidToken:
            raise IntegridadError("fichero de secretos corrupto o clave incorrecta") from None
        contenido: dict[str, dict[str, str]] = json.loads(descifrado)
        return contenido

    def leer(self, ruta: str) -> dict[str, str]:
        contenido = self._cargar()
        if ruta not in contenido:
            raise SecretoNoAccesibleError("secreto no accesible", detalles={"ruta": ruta})
        return dict(contenido[ruta])

    def escribir(self, ruta: str, datos: dict[str, str]) -> None:
        contenido = self._cargar()
        contenido[ruta] = dict(datos)
        self._ruta.write_bytes(self._fernet.encrypt(json.dumps(contenido).encode("utf-8")))


class AlmacenTPM:
    """Secretos sellados por el TPM del appliance: se implementa con el arranque medido."""

    def leer(self, ruta: str) -> dict[str, str]:
        raise NotImplementedError(
            "el sellado de secretos en TPM se implementa en ARG-082 (Fase 09)"
        )
