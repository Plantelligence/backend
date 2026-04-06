import uuid
from sqlalchemy import Boolean, Column, String, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base

class Estufa(Base):
    # Tabela de estufas.
    __tablename__ = "estufas"

    # Identificador unico gerado na aplicacao.
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nome = Column(String, nullable=False)
    
    # UF com duas letras.
    estado = Column(String(2), nullable=False)
    cidade = Column(String, nullable=False)
    cep = Column(String(8), nullable=True)

    # Dono da estufa; exclusao em cascata.
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Preset opcional; ao remover o preset, o campo fica nulo.
    preset_id = Column(String, ForeignKey("presets.id", ondelete="SET NULL"), nullable=True)

    # Equipe responsável específica da estufa (subconjunto dos membros da organização).
    responsible_user_ids = Column(JSON, nullable=False, default=list)

    # Controle de envio de alertas e cooldown de notificação.
    alerts_enabled = Column(Boolean, nullable=False, default=True)
    last_alert_at = Column(String, nullable=True)

    # Relacionamento com usuario.
    user = relationship("User", back_populates="estufas")

    # Relacionamentos dependentes com exclusao em cascata.
    dispositivos = relationship("Dispositivo", back_populates="estufa", cascade="all, delete-orphan")
    
    # Relacionamento com preset.
    preset = relationship("Preset", back_populates="estufas")
    
    # Relacionamento com alertas.
    alertas = relationship("Alertas", back_populates="estufa", cascade="all, delete-orphan")
    
    # Relacionamento com historico.
    historicos = relationship("Historico", back_populates="estufa", cascade="all, delete-orphan")