from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.estufa import Estufa
from app.models.relatorio import Relatorio
from app.schemas.relatorio import CriarRelatorio, RelatorioResposta

router = APIRouter(prefix="/api/estufas", tags=["Relatórios"])


def _verificar_acesso_estufa(db: Session, estufa_id: str, user: dict) -> Estufa:
    # verifica existência e acesso à estufa antes de operar nos relatórios
    from app.services import greenhouse_service as svc
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if not estufa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estufa não encontrada.")
    if not svc._can_access_greenhouse_ids(estufa.id, estufa.user_id, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para acessar esta estufa.")
    return estufa


@router.get("/{estufa_id}/relatorios/resumo")
async def resumo_relatorio(
    estufa_id: str,
    inicio: str = Query(..., description="Data de início no formato YYYY-MM-DD"),
    fim: str = Query(..., description="Data de fim no formato YYYY-MM-DD"),
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Calcula as médias dos 4 sensores no período consultando o InfluxDB."""
    _verificar_acesso_estufa(db, estufa_id, user)

    from app.db.influx.influx import influx_db

    try:
        averages = await influx_db.query_sensor_averages(estufa_id, inicio, fim)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Telemetria indisponível: {exc}",
        )

    def _fmt(val) -> str | None:
        return str(val) if val is not None else None

    return {
        "avg_temperatura": _fmt(averages.get("temperatura")),
        "avg_umidade": _fmt(averages.get("umidade")),
        "avg_umidade_solo": _fmt(averages.get("umidade_solo")),
        "avg_luminosidade": _fmt(averages.get("luminosidade")),
        "tem_dados": bool(averages),
    }


@router.get("/{estufa_id}/relatorios", response_model=list[RelatorioResposta])
async def listar_relatorios(
    estufa_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Lista todos os relatórios da estufa, do mais recente ao mais antigo.
    _verificar_acesso_estufa(db, estufa_id, user)
    rows = (
        db.query(Relatorio)
        .filter(Relatorio.estufa_id == estufa_id)
        .order_by(Relatorio.criado_em.desc())
        .all()
    )
    return rows


@router.post("/{estufa_id}/relatorios", response_model=RelatorioResposta, status_code=status.HTTP_201_CREATED)
async def criar_relatorio(
    estufa_id: str,
    payload: CriarRelatorio,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Cria um relatório periódico para a estufa. Bloqueado para perfil Reader.
    if (user.get("role") or "").strip() == "Reader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Perfil Leitor possui acesso somente de consulta.")
    _verificar_acesso_estufa(db, estufa_id, user)

    novo = Relatorio(
        estufa_id=estufa_id,
        periodo_inicio=payload.periodo_inicio,
        periodo_fim=payload.periodo_fim,
        avg_temperatura=payload.avg_temperatura,
        avg_umidade=payload.avg_umidade,
        avg_umidade_solo=payload.avg_umidade_solo,
        avg_luminosidade=payload.avg_luminosidade,
        resumo=payload.resumo,
        criado_em=datetime.now(timezone.utc).isoformat(),
        criado_por_id=user.get("id"),
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo


@router.delete("/{estufa_id}/relatorios/{relatorio_id}", status_code=status.HTTP_200_OK)
async def remover_relatorio(
    estufa_id: str,
    relatorio_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Remove um relatório. Bloqueado para perfil Reader.
    if (user.get("role") or "").strip() == "Reader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Perfil Leitor possui acesso somente de consulta.")
    _verificar_acesso_estufa(db, estufa_id, user)

    relatorio = db.query(Relatorio).filter(
        Relatorio.id == relatorio_id,
        Relatorio.estufa_id == estufa_id,
    ).first()
    if not relatorio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relatório não encontrado.")

    db.delete(relatorio)
    db.commit()
    return {"deletado_id": relatorio_id}
