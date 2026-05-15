"""
Gerenciamento de dispositivos no Azure IoT Hub via API REST.

O Azure IoT Hub é o serviço de nuvem que recebe os dados enviados pelo ESP32
e permite que o sistema envie comandos de volta ao dispositivo físico.

Para que um ESP32 se conecte ao IoT Hub, ele precisa:
  1. Estar registrado aqui como "dispositivo" (tem um ID único);
  2. Ter uma chave de segurança (SAS Token) que prova que é ele mesmo.

Este módulo cuida de todo esse processo:
  - Gera o token de administrador para fazer chamadas REST ao IoT Hub;
  - Cria o registro do dispositivo e gera o token MQTT para o ESP32;
  - Remove o registro quando o dispositivo é excluído do sistema.

Variáveis de ambiente necessárias:
  IOTHUB_CONNECTION_STRING — connection string completa do IoT Hub (iothubowner)
  IOTHUB_HOST              — hostname do hub (ex.: meuhub.azure-devices.net)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import time
import urllib.parse
from typing import TYPE_CHECKING

import requests

from app.config.settings import settings

if TYPE_CHECKING:
    pass


# ── Geração de SAS Tokens ──────────────────────────────────────────────────────
# SAS Token (Shared Access Signature) é o mecanismo de autenticação do Azure IoT Hub.
# Funciona como uma senha temporária com prazo de validade embutido na assinatura.

def _parse_connection_string(cs: str) -> dict[str, str]:
    """Divide a connection string do IoT Hub em um dicionário chave→valor."""
    return {k: v for k, v in (p.split("=", 1) for p in cs.split(";") if "=" in p)}


def _hub_admin_token(expiry_seconds: int = 3600) -> str:
    """
    Gera o SAS Token de administrador para chamar a API REST do IoT Hub.
    Esse token representa o sistema (não um dispositivo), e tem validade de 1 hora.
    Ele é usado apenas nas chamadas de criação e exclusão de dispositivos.
    """
    cs = settings.iothub_connection_string or ""
    parts = _parse_connection_string(cs)
    hub_host   = parts.get("HostName", "")
    key_name   = parts.get("SharedAccessKeyName", "")
    key        = parts.get("SharedAccessKey", "")

    expiry = int(time.time()) + expiry_seconds
    uri    = hub_host
    # monta a string que será assinada com HMAC-SHA256
    string = f"{urllib.parse.quote(uri, safe='')}\n{expiry}"
    sig    = base64.b64encode(
        hmac.new(base64.b64decode(key), string.encode(), hashlib.sha256).digest()
    ).decode()
    return (
        f"SharedAccessSignature sr={urllib.parse.quote(uri, safe='')}"
        f"&sig={urllib.parse.quote(sig, safe='')}"
        f"&se={expiry}"
        f"&skn={key_name}"
    )


def device_sas_token(device_id: str, device_key: str, expiry_hours: int = 8760) -> str:
    """
    Gera o SAS Token que o ESP32 usa para se autenticar no IoT Hub via MQTT.

    Este token é diferente do token de administrador: ele identifica um dispositivo
    específico e tem validade padrão de 1 ano (8760 horas = 365 dias).
    Quando expirar, o ESP32 não conseguirá mais se conectar — use regenerar-token.

    Parâmetros:
      device_id   — ID do dispositivo registrado no IoT Hub
      device_key  — chave primária do dispositivo (gerada pelo IoT Hub no registro)
      expiry_hours — validade do token em horas (padrão: 1 ano)
    """
    hub_host = settings.iothub_host or ""
    uri      = f"{hub_host}/devices/{device_id}"
    expiry   = int(time.time()) + expiry_hours * 3600
    string   = f"{urllib.parse.quote(uri, safe='')}\n{expiry}"
    sig      = base64.b64encode(
        hmac.new(base64.b64decode(device_key), string.encode(), hashlib.sha256).digest()
    ).decode()
    return (
        f"SharedAccessSignature sr={urllib.parse.quote(uri, safe='')}"
        f"&sig={urllib.parse.quote(sig, safe='')}"
        f"&se={expiry}"
    )


# ── Sanitização do ID do dispositivo ─────────────────────────────────────────
# O IoT Hub exige que o device ID contenha apenas letras, números e os símbolos -._
# Nomes com espaços, acentos ou caracteres especiais precisam ser normalizados.

def _sanitize_device_id(name: str, suffix: str) -> str:
    """
    Converte um nome livre em um device ID válido para o Azure IoT Hub.
    Substitui caracteres especiais por hífens, limita a 40 caracteres e
    adiciona o prefixo "plantelligence-" e um sufixo único para evitar conflitos.
    Comprimento máximo permitido pelo IoT Hub: 128 caracteres.
    """
    safe = re.sub(r"[^a-zA-Z0-9\-._]", "-", name.lower().strip())
    safe = re.sub(r"-+", "-", safe).strip("-")[:40] or "device"
    return f"plantelligence-{safe}-{suffix}"[:128]


# ── Chamadas síncronas à API REST do IoT Hub ─────────────────────────────────
# As chamadas HTTP ao IoT Hub são feitas de forma síncrona (usando requests)
# e executadas em thread separada pelo asyncio (to_thread) para não travar o servidor.

def _create_device_sync(device_id: str) -> dict:
    """
    Registra um novo dispositivo no IoT Hub usando a API REST.
    O IoT Hub retorna o objeto completo, incluindo as chaves de autenticação.
    Lança exceção se o IoT Hub não estiver configurado ou se a chamada falhar.
    """
    hub_host = settings.iothub_host
    if not hub_host:
        raise RuntimeError("IOTHUB_CONNECTION_STRING não configurado.")

    url     = f"https://{hub_host}/devices/{device_id}?api-version=2021-04-12"
    headers = {
        "Authorization": _hub_admin_token(),
        "Content-Type":  "application/json",
    }
    resp = requests.put(url, headers=headers, json={}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _delete_device_sync(device_id: str) -> None:
    """
    Remove o dispositivo do IoT Hub via API REST.
    Ignora erro 404 (dispositivo já removido), mas lança exceção para outros erros.
    """
    hub_host = settings.iothub_host
    if not hub_host:
        return

    url     = f"https://{hub_host}/devices/{device_id}?api-version=2021-04-12"
    headers = {
        "Authorization": _hub_admin_token(),
        "If-Match":      "*",  # aceita qualquer versão do registro
    }
    resp = requests.delete(url, headers=headers, timeout=15)
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()


# ── Interface assíncrona (usada pelas rotas FastAPI) ─────────────────────────

async def create_device(name: str, suffix: str) -> dict:
    """
    Registra o dispositivo no IoT Hub e retorna todas as credenciais necessárias
    para configurar no ESP32 (arquivo boot.py do Wokwi ou hardware real).

    Retorna um dicionário com:
      iothub_device_id  — ID único do dispositivo no IoT Hub
      iothub_primary_key — chave de autenticação (armazenada no banco para renovação)
      iothub_sas_token  — token MQTT pronto para uso (validade 1 ano)
      mqtt_server       — endereço do servidor MQTT (hub.azure-devices.net)
      mqtt_port         — porta MQTT com TLS (sempre 8883)
      mqtt_username     — usuário MQTT no formato exigido pelo IoT Hub
      mqtt_topic_pub    — tópico para o ESP32 publicar dados (telemetria)
      mqtt_topic_sub    — tópico para o ESP32 receber comandos do sistema
    """
    hub_host  = settings.iothub_host or ""
    device_id = _sanitize_device_id(name, suffix)

    data = await asyncio.to_thread(_create_device_sync, device_id)

    primary_key = data["authentication"]["symmetricKey"]["primaryKey"]
    sas_token   = device_sas_token(device_id, primary_key)

    return {
        "iothub_device_id": device_id,
        "iothub_primary_key": primary_key,
        "iothub_sas_token": sas_token,
        # campos prontos para copiar no boot.py do ESP32
        "mqtt_server":    hub_host,
        "mqtt_port":      8883,
        "mqtt_username":  f"{hub_host}/{device_id}/?api-version=2021-04-12",
        "mqtt_topic_pub": f"devices/{device_id}/messages/events/",
        "mqtt_topic_sub": f"devices/{device_id}/messages/devicebound/#",
    }


async def delete_device(device_id: str) -> None:
    """Remove o dispositivo do Azure IoT Hub de forma assíncrona."""
    await asyncio.to_thread(_delete_device_sync, device_id)
