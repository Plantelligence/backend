import uuid
from sqlalchemy import Column, String, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base

class Preset(Base):
    # Tabela de presets de cultivo.
    __tablename__ = "presets"

    # Chave primaria em UUID.
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Indica preset padrao do sistema.
    sistema = Column(Boolean, nullable=False)
    
    # Dono do preset quando personalizado.
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    
    nome_cultura = Column(String, nullable=False)
    tipo_cultura = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    
    # Faixas armazenadas em JSON.
    temperatura = Column(JSON, nullable=False)
    umidade = Column(JSON, nullable=False)
    luminosidade = Column(JSON, nullable=False)
    
    # Relacionamento reverso com estufas.
    estufas = relationship("Estufa", back_populates="preset")
