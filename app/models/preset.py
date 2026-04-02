import uuid
from sqlalchemy import Column, String, Float
from sqlalchemy.orm import relationship
from app.db.postgres import Base

class Preset(Base):
    #criando a tabela "preset" no banco de dados PostgreSQL passando a classe Base como parametro
    __tablename__ = "presets"

    #colunas da tabela preset
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nome_cultura = Column(String, nullable=False)
    tipo_cultura = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    temperatura_minima = Column(Float, nullable=False)
    temperatura_maxima = Column(Float, nullable=False)
    umidade_minima = Column(Float, nullable=False)
    umidade_maxima = Column(Float, nullable=False)
    luz_minima = Column(Float, nullable=False)
    luz_maxima = Column(Float, nullable=False)
    
    #relacionamento com a tabela estufa
    estufas = relationship("Estufa", back_populates="preset")
    
    
    
