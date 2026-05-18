from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.estufa import Estufa
from app.models.relatorio import Relatorio
from app.schemas.relatorio import CriarRelatorio, GerarRelatorioRequest, RelatorioResposta

router = APIRouter(prefix="/api/estufas", tags=["Relatórios"])


def _verificar_acesso_estufa(db: Session, estufa_id: str, user: dict) -> None:
    from app.services import greenhouse_service as svc
    try:
        svc.buscar_estufa(db, estufa_id, user)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estufa não encontrada.")
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para acessar esta estufa.")


@router.get("/{estufa_id}/relatorios/{relatorio_id}", response_model=RelatorioResposta)
async def obter_relatorio(
    estufa_id: str,
    relatorio_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Obtem um relatorio especifico pelo ID."""
    _verificar_acesso_estufa(db, estufa_id, user)

    relatorio = db.query(Relatorio).filter(
        Relatorio.id == relatorio_id,
        Relatorio.estufa_id == estufa_id,
    ).first()
    if not relatorio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relatório não encontrado.")
    return relatorio


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


@router.get("/{estufa_id}/relatorios")
async def listar_relatorios(
    estufa_id: str,
    page: int = Query(default=1, ge=1, description="Numero da pagina"),
    page_size: int = Query(default=20, ge=1, le=100, description="Itens por pagina"),
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista relatorios da estufa com paginacao, do mais recente ao mais antigo."""
    _verificar_acesso_estufa(db, estufa_id, user)

    total = (
        db.query(Relatorio)
        .filter(Relatorio.estufa_id == estufa_id)
        .count()
    )

    offset = (page - 1) * page_size
    rows = (
        db.query(Relatorio)
        .filter(Relatorio.estufa_id == estufa_id)
        .order_by(Relatorio.criado_em.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return {
        "relatorios": [RelatorioResposta.model_validate(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


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
        auto_generated=False,
        alert_count=0,
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo


@router.post("/{estufa_id}/relatorios/generate", response_model=RelatorioResposta, status_code=status.HTTP_201_CREATED)
async def gerar_relatorio_automatico(
    estufa_id: str,
    payload: GerarRelatorioRequest,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Gera automaticamente um relatorio a partir dos dados do InfluxDB
    para o periodo informado. Bloqueado para perfil Reader.
    """
    if (user.get("role") or "").strip() == "Reader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Perfil Leitor possui acesso somente de consulta.")
    _verificar_acesso_estufa(db, estufa_id, user)

    from app.db.influx.influx import influx_db

    try:
        averages = await influx_db.query_sensor_averages(
            estufa_id, payload.periodo_inicio, payload.periodo_fim
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Telemetria indisponível: {exc}",
        )

    if not averages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum dado de sensor encontrado para o periodo informado.",
        )

    def _fmt(val) -> str | None:
        return str(val) if val is not None else None

    novo = Relatorio(
        estufa_id=estufa_id,
        periodo_inicio=payload.periodo_inicio,
        periodo_fim=payload.periodo_fim,
        avg_temperatura=_fmt(averages.get("temperatura")),
        avg_umidade=_fmt(averages.get("umidade")),
        avg_umidade_solo=_fmt(averages.get("umidade_solo")),
        avg_luminosidade=_fmt(averages.get("luminosidade")),
        resumo=None,
        criado_em=datetime.now(timezone.utc).isoformat(),
        criado_por_id=user.get("id"),
        auto_generated=True,
        alert_count=0,
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo


@router.get("/{estufa_id}/relatorios/export")
async def exportar_relatorios(
    estufa_id: str,
    format: str = Query(default="csv", regex="^(csv|xlsx|pdf)$", description="Formato de exportacao: csv, xlsx ou pdf"),
    periodo_inicio: str | None = Query(default=None, description="Filtrar a partir desta data (YYYY-MM-DD)"),
    periodo_fim: str | None = Query(default=None, description="Filtrar ate esta data (YYYY-MM-DD)"),
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exporta relatorios da estufa em CSV, XLSX ou PDF."""
    _verificar_acesso_estufa(db, estufa_id, user)

    query = (
        db.query(Relatorio)
        .filter(Relatorio.estufa_id == estufa_id)
        .order_by(Relatorio.criado_em.desc())
    )

    if periodo_inicio:
        query = query.filter(Relatorio.periodo_inicio >= periodo_inicio)
    if periodo_fim:
        query = query.filter(Relatorio.periodo_fim <= periodo_fim)

    relatorios = query.all()

    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    estufa_nome = estufa.nome if estufa else estufa_id

    from app.services.report_export_service import export_csv, export_pdf, export_xlsx

    if format == "csv":
        content = export_csv(relatorios, estufa_nome)
        media_type = "text/csv; charset=utf-8"
        filename = f"relatorios_{estufa_nome}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    elif format == "xlsx":
        content = export_xlsx(relatorios, estufa_nome)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"relatorios_{estufa_nome}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.xlsx"
    else:
        content = export_pdf(relatorios, estufa_nome)
        media_type = "application/pdf"
        filename = f"relatorios_{estufa_nome}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
