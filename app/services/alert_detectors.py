"""
Detectores automaticos de alertas — rodam em background como tarefas asyncio.

Cada detector verifica uma condicao especifica em intervalos regulares e,
quando detecta um problema, despacha notificacoes via NotificationEngine.

Detectores implementados:
  1. MetricMonitor     — metricas fora da faixa e sensores sem dados (A1-A5)
  2. DeviceMonitor     — dispositivos desconectados/reconectados (B1-B2)
  3. WeatherMonitor    — alertas climaticos (C1-C6)
  4. AnomalyDetector   — picos anomalous (A3)
  5. TokenMonitor      — tokens SAS expirando/expirados (B3-B4)
  6. ReportGenerator   — relatorios semanais automaticos (F1)

Todos rodam em loop com asyncio.sleep entre iteracoes.
Sao iniciados automaticamente no startup do FastAPI via main.py.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.postgres.session import get_session
from app.models.estufa import Estufa
from app.models.dispositivo import Dispositivo
from app.models.user import User
from app.models.preset import Preset

logger = logging.getLogger(__name__)

# Intervalos de execucao (segundos)
METRIC_MONITOR_INTERVAL = 120       # 2 min
DEVICE_MONITOR_INTERVAL = 300       # 5 min
WEATHER_MONITOR_INTERVAL = 1800     # 30 min
ANOMALY_DETECTOR_INTERVAL = 300     # 5 min
TOKEN_MONITOR_INTERVAL = 3600       # 1h
REPORT_GENERATOR_INTERVAL = 86400   # 24h (verifica se e dia de gerar semanal)

# Thresholds
SENSOR_OFFLINE_MINUTES = 15
DEVICE_DISCONNECTED_MINUTES = 10
ANOMALY_VARIATION_PERCENT = 30
TOKEN_EXPIRY_WARNING_DAYS = 30


async def start_alert_detectors() -> None:
    """Inicia todos os detectores em paralelo como tarefas asyncio."""
    tasks = [
        asyncio.create_task(_run_metric_monitor(), name="metric-monitor"),
        asyncio.create_task(_run_device_monitor(), name="device-monitor"),
        asyncio.create_task(_run_weather_monitor(), name="weather-monitor"),
        asyncio.create_task(_run_anomaly_detector(), name="anomaly-detector"),
        asyncio.create_task(_run_token_monitor(), name="token-monitor"),
        asyncio.create_task(_run_report_generator(), name="report-generator"),
    ]
    logger.info("Alert detectors started: %d tasks", len(tasks))


# ── MetricMonitor (A1-A5) ──────────────────────────────────────────────────

async def _run_metric_monitor() -> None:
    """
    Verifica a cada 2 minutos se as metricas das estufas estao dentro da faixa.

    Alertas gerados:
      A1 — metrica fora da faixa
      A2 — sensor sem dados (offline)
      A4 — multiplas metricas criticas
      A5 — metrica retornou ao normal
    """
    while True:
        try:
            await _check_metrics()
        except Exception as exc:
            logger.error("metric_monitor_error: %s", exc)
        await asyncio.sleep(METRIC_MONITOR_INTERVAL)


async def _check_metrics() -> None:
    """Verifica metricas de todas as estufas ativas."""
    from app.services.notification_engine import get_notification_engine
    from app.db.influx.influx import influx_db

    engine = get_notification_engine()

    with get_session() as db:
        estufas = db.query(Estufa).all()

    for estufa in estufas:
        try:
            await _check_estufa_metrics(estufa, engine, influx_db)
        except Exception as exc:
            logger.error("metric_check_error estufa_id=%s: %s", estufa.id, exc)


async def _check_estufa_metrics(estufa, engine, influx_db) -> None:
    """Verifica metricas de uma estufa especifica."""
    preset = None
    if estufa.preset_id:
        with get_session() as db:
            preset = db.query(Preset).filter(Preset.id == estufa.preset_id).first()

    if not preset:
        return  # sem preset = sem faixa ideal para comparar

    # buscar ultimas leituras do InfluxDB (ultimos 5 minutos)
    now = datetime.now(timezone.utc)
    five_min_ago = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        averages = await influx_db.query_sensor_averages_range(
            estufa_id=estufa.id,
            start=five_min_ago,
            stop=now_iso,
        )
    except Exception:
        averages = {}

    if not averages:
        # sem dados nos ultimos 5 minutos — verificar se ja tem alerta de offline
        last_data = await _get_last_telemetry_time(influx_db, estufa.id)
        if last_data and (now - last_data).total_seconds() > SENSOR_OFFLINE_MINUTES * 60:
            await _dispatch_sensor_offline(estufa, engine)
        return

    # verificar cada metrica contra o preset
    ranges = {
        "temperatura": _parse_range(preset.temperatura),
        "umidade": _parse_range(preset.umidade),
        "umidade_solo": _parse_range(preset.umidade_solo),
        "luminosidade": _parse_range(preset.luminosidade),
    }

    labels = {
        "temperatura": "Temperatura",
        "umidade": "Umidade do ar",
        "umidade_solo": "Umidade do solo",
        "luminosidade": "Luminosidade",
    }

    out_of_range_count = 0
    for metric_name, value in averages.items():
        expected = ranges.get(metric_name)
        if not expected or value is None:
            continue

        if value < expected["min"] or value > expected["max"]:
            out_of_range_count += 1
            direction = "abaixo" if value < expected["min"] else "acima"
            engine.dispatch(
                user_id=estufa.user_id,
                notification_type="metric_out_of_range",
                severity="warning",
                title=f"{labels.get(metric_name, metric_name)} fora do ideal",
                message=(
                    f"A {labels.get(metric_name, metric_name).lower()} da estufa "
                    f"'{estufa.nome}' esta {direction} do ideal: "
                    f"{value:.1f} (faixa: {expected['min']}-{expected['max']})."
                ),
                greenhouse_id=estufa.id,
                metadata={
                    "metric": metric_name,
                    "value": value,
                    "expected_min": expected["min"],
                    "expected_max": expected["max"],
                    "direction": direction,
                },
            )

    # A4 — multiplas metricas criticas
    if out_of_range_count >= 2:
        engine.dispatch(
            user_id=estufa.user_id,
            notification_type="multiple_critical",
            severity="critical",
            title=f"Multiplas metricas criticas — {estufa.nome}",
            message=(
                f"{out_of_range_count} metricas fora da faixa ideal na estufa "
                f"'{estufa.nome}'. Verifique imediatamente."
            ),
            greenhouse_id=estufa.id,
            metadata={"out_of_range_count": out_of_range_count},
        )

    # responsaveis tambem recebem
    responsaveis = estufa.responsible_user_ids or []
    if responsaveis:
        for resp_id in responsaveis:
            if out_of_range_count >= 1:
                engine.dispatch(
                    user_id=resp_id,
                    notification_type="metric_out_of_range",
                    severity="warning",
                    title=f"Alerta na estufa {estufa.nome}",
                    message=(
                        f"{out_of_range_count} metrica(s) fora da faixa ideal na estufa "
                        f"'{estufa.nome}' da qual voce e responsavel."
                    ),
                    greenhouse_id=estufa.id,
                    metadata={"out_of_range_count": out_of_range_count},
                )


async def _dispatch_sensor_offline(estufa, engine) -> None:
    """Alerta A2 — sensor sem dados."""
    engine.dispatch(
        user_id=estufa.user_id,
        notification_type="sensor_offline",
        severity="warning",
        title=f"Sensor sem dados — {estufa.nome}",
        message=(
            f"A estufa '{estufa.nome}' nao envia dados de telemetria "
            f"ha mais de {SENSOR_OFFLINE_MINUTES} minutos. Verifique os dispositivos."
        ),
        greenhouse_id=estufa.id,
        metadata={"offline_minutes": SENSOR_OFFLINE_MINUTES},
    )


async def _get_last_telemetry_time(influx_db, estufa_id: str) -> datetime | None:
    """Retorna o timestamp da ultima leitura de telemetria."""
    try:
        now = datetime.now(timezone.utc)
        one_hour_ago = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        query = (
            f'from(bucket: "{influx_db._client._read_response_timeout}")\n'
            f'  |> range(start: {one_hour_ago}, stop: {now_iso})\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria_estufa")\n'
            f'  |> filter(fn: (r) => r.estufa_id == "{estufa_id}")\n'
            f'  |> last()'
        )
        tables = await influx_db.query(query)
        for table in tables:
            for record in table.records:
                return record.get_time()
    except Exception:
        pass
    return None


# ── DeviceMonitor (B1-B2) ─────────────────────────────────────────────────

async def _run_device_monitor() -> None:
    """
    Verifica a cada 5 minutos o status dos dispositivos no IoT Hub.

    Alertas gerados:
      B1 — dispositivo desconectado
      B2 — dispositivo reconectado
    """
    # rastrear estado anterior para detectar reconexao
    previous_states: dict[str, bool] = {}

    while True:
        try:
            previous_states = await _check_devices(previous_states)
        except Exception as exc:
            logger.error("device_monitor_error: %s", exc)
        await asyncio.sleep(DEVICE_MONITOR_INTERVAL)


async def _check_devices(previous_states: dict[str, bool]) -> dict[str, bool]:
    """Verifica status de todos os dispositivos com credenciais IoT Hub."""
    from app.services.notification_engine import get_notification_engine

    engine = get_notification_engine()
    current_states: dict[str, bool] = {}

    with get_session() as db:
        dispositivos = (
            db.query(Dispositivo)
            .filter(Dispositivo.iothub_device_id.isnot(None))
            .all()
        )

    for dispositivo in dispositivos:
        device_id = dispositivo.iothub_device_id
        is_connected = False

        try:
            from app.services.iothub_command_service import get_command_service
            service = get_command_service()
            twin = await service.get_device_twin(device_id)
            is_connected = twin.get("connectionState") == "Connected"

            # atualizar last_seen_at no banco
            dispositivo.last_seen_at = datetime.now(timezone.utc).isoformat()
            db.commit()

        except Exception:
            is_connected = False

        current_states[dispositivo.id] = is_connected

        # B1 — desconectou
        if previous_states.get(dispositivo.id) is True and not is_connected:
            estufa = db.query(Estufa).filter(Estufa.id == dispositivo.estufa_id).first()
            if estufa:
                engine.dispatch(
                    user_id=estufa.user_id,
                    notification_type="device_disconnected",
                    severity="warning",
                    title=f"Dispositivo desconectado — {dispositivo.nome}",
                    message=(
                        f"O dispositivo '{dispositivo.nome}' da estufa "
                        f"'{estufa.nome}' perdeu conexao com o IoT Hub."
                    ),
                    greenhouse_id=estufa.id,
                    metadata={
                        "dispositivoId": dispositivo.id,
                        "dispositivoNome": dispositivo.nome,
                        "dispositivoTipo": dispositivo.tipo,
                    },
                )

        # B2 — reconectou
        elif previous_states.get(dispositivo.id) is False and is_connected:
            estufa = db.query(Estufa).filter(Estufa.id == dispositivo.estufa_id).first()
            if estufa:
                engine.dispatch(
                    user_id=estufa.user_id,
                    notification_type="device_reconnected",
                    severity="info",
                    title=f"Dispositivo reconectado — {dispositivo.nome}",
                    message=(
                        f"O dispositivo '{dispositivo.nome}' da estufa "
                        f"'{estufa.nome}' restabeleceu conexao com o IoT Hub."
                    ),
                    greenhouse_id=estufa.id,
                    metadata={
                        "dispositivoId": dispositivo.id,
                        "dispositivoNome": dispositivo.nome,
                    },
                )

    db.close()
    return current_states


# ── WeatherMonitor (C1-C6) ────────────────────────────────────────────────

async def _run_weather_monitor() -> None:
    """
    Verifica a cada 30 minutos alertas climaticos para todas as estufas.

    Alertas gerados:
      C1 — onda de calor (> 35°C)
      C2 — geada (< 5°C)
      C3 — tempestade (chuva > 70%)
      C4 — vento forte (> 60 km/h)
      C5 — mudanca brusca (diferenca > 10°C)
      C6 — recomendacao de ajuste
    """
    # cache do ultimo clima por estufa para detectar mudanca brusca
    previous_weather: dict[str, dict] = {}

    while True:
        try:
            previous_weather = await _check_weather(previous_weather)
        except Exception as exc:
            logger.error("weather_monitor_error: %s", exc)
        await asyncio.sleep(WEATHER_MONITOR_INTERVAL)


async def _check_weather(previous_weather: dict[str, dict]) -> dict[str, dict]:
    """Verifica alertas climaticos para todas as estufas."""
    from app.services.notification_engine import get_notification_engine
    from app.services import weather_service

    engine = get_notification_engine()
    current_weather: dict[str, dict] = {}

    with get_session() as db:
        estufas = db.query(Estufa).all()

    for estufa in estufas:
        if not estufa.cidade or not estufa.estado:
            continue

        try:
            clima = await weather_service.buscar_clima_externo_atual(
                estufa.cidade, estufa.estado
            )
            current_weather[estufa.id] = clima

            temperatura = clima.get("temperatura")
            umidade = clima.get("umidade")
            nuvens = clima.get("nuvens")
            condicao = (clima.get("condicao") or "").lower()

            # C1 — onda de calor
            if temperatura and temperatura >= 35:
                engine.dispatch(
                    user_id=estufa.user_id,
                    notification_type="weather_heat_wave",
                    severity="warning",
                    title=f"Onda de calor prevista — {estufa.nome}",
                    message=(
                        f"Temperatura externa de {temperatura:.1f}°C prevista para "
                        f"{estufa.cidade}/{estufa.estado}. Reforce a ventilacao da estufa."
                    ),
                    greenhouse_id=estufa.id,
                    metadata={"temperature": temperatura, "city": estufa.cidade, "state": estufa.estado},
                )

            # C2 — geada
            if temperatura and temperatura <= 5:
                engine.dispatch(
                    user_id=estufa.user_id,
                    notification_type="weather_frost",
                    severity="warning",
                    title=f"Risco de geada — {estufa.nome}",
                    message=(
                        f"Temperatura externa de {temperatura:.1f}°C prevista para "
                        f"{estufa.cidade}/{estufa.estado}. Ative o aquecimento e proteja os substratos."
                    ),
                    greenhouse_id=estufa.id,
                    metadata={"temperature": temperatura, "city": estufa.cidade, "state": estufa.estado},
                )

            # C3 — tempestade
            # OpenWeather current nao tem POP, mas podemos inferir pela condicao
            if condicao in ("rain", "drizzle", "thunderstorm"):
                engine.dispatch(
                    user_id=estufa.user_id,
                    notification_type="weather_storm",
                    severity="warning",
                    title=f"Chuva detectada — {estufa.nome}",
                    message=(
                        f"Condicao climatica '{clima.get('descricao')}' em "
                        f"{estufa.cidade}/{estufa.estado}. Verifique a vedacao da estufa."
                    ),
                    greenhouse_id=estufa.id,
                    metadata={"condition": condicao, "city": estufa.cidade, "state": estufa.estado},
                )

            # C4 — vento forte (estimado pela condicao e nuvens)
            # OpenWeather current nao tem vento maximo, mas podemos alertar por condicao severa
            if condicao in ("thunderstorm", "tornado", "hurricane") or (nuvens and nuvens > 90):
                engine.dispatch(
                    user_id=estufa.user_id,
                    notification_type="weather_strong_wind",
                    severity="warning",
                    title=f"Condicao climatica severa — {estufa.nome}",
                    message=(
                        f"Condicao '{clima.get('descricao')}' com {nuvens}% de nuvens em "
                        f"{estufa.cidade}/{estufa.estado}. Fixe estruturas expostas e verifique a cobertura."
                    ),
                    greenhouse_id=estufa.id,
                    metadata={"condition": condicao, "clouds": nuvens, "city": estufa.cidade, "state": estufa.estado},
                )

            # C5 — mudanca brusca de temperatura
            prev = previous_weather.get(estufa.id)
            if prev and prev.get("temperatura") and temperatura:
                diff = abs(temperatura - prev["temperatura"])
                if diff > 10:
                    direction = "subiu" if temperatura > prev["temperatura"] else "caiu"
                    engine.dispatch(
                        user_id=estufa.user_id,
                        notification_type="weather_sudden_change",
                        severity="warning",
                        title=f"Mudanca brusca de temperatura — {estufa.nome}",
                        message=(
                            f"A temperatura externa {direction} {diff:.1f}°C em {estufa.cidade}/{estufa.estado} "
                            f"(de {prev['temperatura']:.1f}°C para {temperatura:.1f}°C). "
                            f"Ajuste os parametros da estufa."
                        ),
                        greenhouse_id=estufa.id,
                        metadata={
                            "previous_temp": prev["temperatura"],
                            "current_temp": temperatura,
                            "diff": diff,
                            "direction": direction,
                            "city": estufa.cidade,
                            "state": estufa.estado,
                        },
                    )

            # C6 — recomendacao de ajuste baseada no clima
            recommendations = _generate_weather_recommendations(
                temperatura, umidade, condicao, estufa
            )
            for rec in recommendations:
                engine.dispatch(
                    user_id=estufa.user_id,
                    notification_type="weather_recommendation",
                    severity="info",
                    title=f"Recomendacao climatica — {estufa.nome}",
                    message=rec,
                    greenhouse_id=estufa.id,
                    metadata={"city": estufa.cidade, "state": estufa.estado},
                )

        except Exception as exc:
            logger.warning("weather_check_error estufa_id=%s: %s", estufa.id, exc)

    return current_weather


def _generate_weather_recommendations(temperatura, umidade, condicao, estufa) -> list[str]:
    """Gera recomendacoes praticas baseadas no clima atual."""
    recs = []

    if temperatura and temperatura > 30:
        recs.append(
            f"Temperatura alta em {estufa.cidade}. Considere aumentar a ventilacao "
            f"e ativar o sombreamento da estufa '{estufa.nome}'."
        )

    if umidade and umidade < 40:
        recs.append(
            f"Umidade externa baixa em {estufa.cidade} ({umidade}%). "
            f"Monitore a umidade interna da estufa '{estufa.nome}' para evitar ressecamento."
        )

    if condicao == "clear":
        recs.append(
            f"Ceu limpo em {estufa.cidade}. Boa condicao para ventilacao natural "
            f"na estufa '{estufa.nome}'."
        )

    return recs


# ── AnomalyDetector (A3) ──────────────────────────────────────────────────

async def _run_anomaly_detector() -> None:
    """
    Verifica a cada 5 minutos picos anomalous nas metricas.

    Alerta gerado:
      A3 — variacao > 30% em relacao a media dos ultimos 30 minutos
    """
    while True:
        try:
            await _check_anomalies()
        except Exception as exc:
            logger.error("anomaly_detector_error: %s", exc)
        await asyncio.sleep(ANOMALY_DETECTOR_INTERVAL)


async def _check_anomalies() -> None:
    """Verifica anomalias em todas as estufas."""
    from app.services.notification_engine import get_notification_engine
    from app.db.influx.influx import influx_db

    engine = get_notification_engine()

    with get_session() as db:
        estufas = db.query(Estufa).all()

    for estufa in estufas:
        try:
            # media dos ultimos 30 min
            now = datetime.now(timezone.utc)
            thirty_min_ago = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            five_min_ago = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            avg_30 = await influx_db.query_sensor_averages_range(
                estufa_id=estufa.id,
                start=thirty_min_ago,
                stop=five_min_ago,
            )
            avg_5 = await influx_db.query_sensor_averages_range(
                estufa_id=estufa.id,
                start=five_min_ago,
                stop=now_iso,
            )

            labels = {
                "temperatura": "Temperatura",
                "umidade": "Umidade do ar",
                "umidade_solo": "Umidade do solo",
                "luminosidade": "Luminosidade",
            }

            for metric, value_recent in avg_5.items():
                value_old = avg_30.get(metric)
                if value_old and value_old != 0 and value_recent:
                    variation = abs(value_recent - value_old) / abs(value_old) * 100
                    if variation > ANOMALY_VARIATION_PERCENT:
                        engine.dispatch(
                            user_id=estufa.user_id,
                            notification_type="anomaly_detected",
                            severity="warning",
                            title=f"Variacao anomala — {labels.get(metric, metric)}",
                            message=(
                                f"A {labels.get(metric, metric).lower()} da estufa "
                                f"'{estufa.nome}' variou {variation:.0f}% nos ultimos 5 minutos "
                                f"(de {value_old:.1f} para {value_recent:.1f})."
                            ),
                            greenhouse_id=estufa.id,
                            metadata={
                                "metric": metric,
                                "old_value": value_old,
                                "new_value": value_recent,
                                "variation_percent": round(variation, 1),
                            },
                        )

        except Exception as exc:
            logger.warning("anomaly_check_error estufa_id=%s: %s", estufa.id, exc)


# ── TokenMonitor (B3-B4) ──────────────────────────────────────────────────

async def _run_token_monitor() -> None:
    """
    Verifica a cada hora tokens SAS prestes a expirar ou expirados.

    Alertas gerados:
      B3 — token expirando em menos de 30 dias
      B4 — token expirado
    """
    while True:
        try:
            await _check_tokens()
        except Exception as exc:
            logger.error("token_monitor_error: %s", exc)
        await asyncio.sleep(TOKEN_MONITOR_INTERVAL)


async def _check_tokens() -> None:
    """Verifica tokens SAS de todos os dispositivos."""
    from app.services.notification_engine import get_notification_engine

    engine = get_notification_engine()
    now = datetime.now(timezone.utc)
    warning_threshold = now + timedelta(days=TOKEN_EXPIRY_WARNING_DAYS)

    with get_session() as db:
        dispositivos = (
            db.query(Dispositivo)
            .filter(
                Dispositivo.iothub_device_id.isnot(None),
                Dispositivo.ativo.is_(True),
            )
            .all()
        )

    for dispositivo in dispositivos:
        # SAS tokens sao regenerados sob demanda, mas podemos alertar
        # se o dispositivo nao se conecta ha muito tempo (possivel token expirado)
        if dispositivo.iothub_sas_token is None:
            # token nao persistido no banco — verificar ultima conexao
            last_seen = dispositivo.last_seen_at if hasattr(dispositivo, "last_seen_at") else None
            if last_seen:
                last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                days_since = (now - last_seen_dt).days
                if days_since > 365:
                    estufa = db.query(Estufa).filter(Estufa.id == dispositivo.estufa_id).first()
                    if estufa:
                        engine.dispatch(
                            user_id=estufa.user_id,
                            notification_type="token_expired",
                            severity="critical",
                            title=f"Token possivelmente expirado — {dispositivo.nome}",
                            message=(
                                f"O dispositivo '{dispositivo.nome}' nao se conecta "
                                f"ha {days_since} dias. O token SAS pode ter expirado. "
                                f"Regenere o token no dashboard."
                            ),
                            greenhouse_id=estufa.id,
                            metadata={
                                "dispositivoId": dispositivo.id,
                                "dispositivoNome": dispositivo.nome,
                                "days_since_connection": days_since,
                            },
                        )

    db.close()


# ── ReportGenerator (F1) ──────────────────────────────────────────────────

async def _run_report_generator() -> None:
    """
    Verifica diariamente se e dia de gerar relatorio semanal.

    Alerta gerado:
      F1 — relatorio semanal disponivel
    """
    last_run_date = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            # gerar relatorio toda segunda-feira as 08:00 UTC
            if now.weekday() == 0 and now.hour == 8:  # segunda
                if last_run_date != now.date():
                    await _generate_weekly_reports()
                    last_run_date = now.date()
        except Exception as exc:
            logger.error("report_generator_error: %s", exc)
        await asyncio.sleep(REPORT_GENERATOR_INTERVAL)


async def _generate_weekly_reports() -> None:
    """Gera relatorios semanais para todas as estufas."""
    from app.services.notification_engine import get_notification_engine

    engine = get_notification_engine()

    with get_session() as db:
        estufas = db.query(Estufa).all()

    for estufa in estufas:
        try:
            engine.dispatch(
                user_id=estufa.user_id,
                notification_type="weekly_report",
                severity="info",
                title=f"Relatorio semanal — {estufa.nome}",
                message=(
                    f"O relatorio semanal da estufa '{estufa.nome}' esta disponivel. "
                    f"Consulte o dashboard para ver as medias e alertas da semana."
                ),
                greenhouse_id=estufa.id,
                metadata={"reportPeriod": "weekly"},
            )
        except Exception as exc:
            logger.warning("weekly_report_error estufa_id=%s: %s", estufa.id, exc)

    db.close()


# ── Utilitarios ────────────────────────────────────────────────────────────

def _parse_range(value: Any) -> dict[str, float] | None:
    """Parse de um range de preset (pode ser dict ou JSON string)."""
    if not value:
        return None
    if isinstance(value, dict):
        min_v = value.get("min")
        max_v = value.get("max")
        if min_v is not None and max_v is not None:
            return {"min": float(min_v), "max": float(max_v)}
    return None
