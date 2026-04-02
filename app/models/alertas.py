import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres import Base

#criando a tabela "alertas" no banco de dados PostgreSQL passando a classe Base como parametro
class Alertas(Base):
    __tablename__ = "alertas"

    #colunas da tabela alertas
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tipo = Column(String, nullable=False)
    mensagem = Column(String, nullable=False)
    
    # chaves estrangeiras para as tabelas estufa, dispositivo e user
    estufa_id = Column(String, ForeignKey("estufas.id"), nullable=False)
    dispositivo_id = Column(String, ForeignKey("dispositivos.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    #relacionamento com a tabela estufa
    estufa = relationship("Estufa", back_populates="alertas")
    #relacionamento com a tabela dispositivo
    dispositivo = relationship("Dispositivo", back_populates="alertas")
    #relacionamento com a tabela user
    user = relationship("User", back_populates="alertas")