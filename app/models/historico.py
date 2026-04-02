import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base

# Model base p/ registrar os logs de operacoes que um cara fez na nossa plataforma
class Historico(Base):
    __tablename__ = "historicos"

    # Sempre o id padrao por uuid gerado na hora pelo app (pra dar menos trampo pro db)
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Campo tipo enum de O QUE aconteceu (ex: "Liga ar", "Apaga luz")
    acao = Column(String, nullable=False)
    
    # Da onda veio (App, Automacao pre setada, Sensor local)
    origem = Column(String, nullable=False)

    # Pra gente saber exatamente ONDE, COM O QUE, e QUEM mexeu na estufa.
    # Sem nullable=true por razoes obvias, log fake ngm quer.
    estufa_id = Column(String, ForeignKey("estufas.id"), nullable=False)
    dispositivo_id = Column(String, ForeignKey("dispositivos.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    # Pra n precisar dar 3 left joins qnd puxar do historico...
    estufa = relationship("Estufa", back_populates="historicos")
    dispositivo = relationship("Dispositivo", back_populates="historicos")
    user = relationship("User", back_populates="historicos")