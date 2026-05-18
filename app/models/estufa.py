"""
Modelo de banco de dados para estufas (unidades de cultivo).

A estufa é o recurso central do sistema — tudo gira em torno dela.
Cada estufa pertence a um usuário (dono), pode ter vários membros responsáveis,
um perfil de cultivo (preset) vinculado, dispositivos IoT, alertas e relatórios.

Sobre `responsible_user_ids`:
  Lista de IDs de usuários da mesma organização que têm acesso à estufa,
  além do dono. Armazenado como JSON para evitar tabela de relacionamento N:N.

Sobre `alert_thresholds`:
  JSON com limites personalizados por sensor. Se definido, sobrescreve os limites
  do preset vinculado. Formato esperado:
    { "temperatura": {"min": 18, "max": 24}, "umidade": {"min": 80, "max": 95} }
"""

import uuid
from sqlalchemy import Boolean, Column, String, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base


class Estufa(Base):
    __tablename__ = "estufas"

    id     = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nome   = Column(String, nullable=False)
    estado = Column(String(2), nullable=False)   # UF com 2 letras (ex.: SP, PR)
    cidade = Column(String, nullable=False)
    cep    = Column(String(8), nullable=True)     # usado para buscar clima externo

    # dono da estufa — remoção em cascata
    user_id   = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # perfil de cultivo — SET NULL ao remover o preset (não perde a estufa)
    preset_id = Column(String, ForeignKey("presets.id", ondelete="SET NULL"), nullable=True)

    # membros com acesso além do dono (subconjunto da organização)
    responsible_user_ids = Column(JSON, nullable=False, default=list)

    # controle de alertas por e-mail
    alerts_enabled  = Column(Boolean, nullable=False, default=True)
    last_alert_at   = Column(String, nullable=True)    # cooldown: evita spam de alertas
    alert_thresholds = Column(JSON, nullable=True)

    user        = relationship("User",       back_populates="estufas")
    preset      = relationship("Preset",     back_populates="estufas")
    dispositivos = relationship("Dispositivo", back_populates="estufa",  cascade="all, delete-orphan")
    alertas     = relationship("Alertas",    back_populates="estufa",   cascade="all, delete-orphan")
    relatorios  = relationship("Relatorio",  back_populates="estufa",   cascade="all, delete-orphan")
    historicos  = relationship("Historico",  back_populates="estufa",   cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="greenhouse")
