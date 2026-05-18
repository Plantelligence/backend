"""
Schemas Pydantic para notificacoes e preferencias.

Tipos de notificacao suportados:
  metric_out_of_range, sensor_offline, anomaly_detected, multiple_critical,
  metric_recovered, device_disconnected, device_reconnected,
  token_expiring, token_expired, device_created, device_removed,
  weather_heat_wave, weather_frost, weather_storm, weather_strong_wind,
  weather_sudden_change, weather_recommendation,
  automation_action, automation_failure, preset_changed,
  invitation_expired, password_expiring, demo_expiring,
  new_team_member, weekly_report, monthly_summary
"""

from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    """Resposta de uma unica notificacao."""
    id: str
    userId: str
    notificationType: str
    severity: str
    title: str
    message: str
    metadata: dict | None = None
    greenhouseId: str | None = None
    read: bool
    readAt: str | None = None
    dismissedAt: str | None = None
    createdAt: str | None = None

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """Resposta paginada de lista de notificacoes."""
    notifications: list[NotificationResponse]
    total: int
    unread_count: int


class NotificationPreferenceResponse(BaseModel):
    """Preferencias de notificacao do usuario."""
    id: str
    userId: str
    channelEmail: bool
    channelInapp: bool
    blockedTypes: list[str]
    quietHoursStart: str | None = None
    quietHoursEnd: str | None = None
    quietHoursIncludeWarning: bool

    model_config = ConfigDict(from_attributes=True)


class UpdateNotificationPreferenceRequest(BaseModel):
    """Payload para atualizar preferencias de notificacao."""
    channelEmail: bool | None = None
    channelInapp: bool | None = None
    blockedTypes: list[str] | None = None
    quietHoursStart: str | None = None
    quietHoursEnd: str | None = None
    quietHoursIncludeWarning: bool | None = None


class NotificationFilterParams(BaseModel):
    """Parametros de filtro para listagem de notificacoes."""
    type: str | None = None
    severity: str | None = None
    greenhouse_id: str | None = None
    read: bool | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
