# backend

Back-end do Plantelligence — FastAPI + PostgreSQL + InfluxDB.

## Como rodar localmente

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copie `.env.example` para `.env` e preencha os valores.

```bash
uvicorn app.main:app --reload --port 4001
```

A API fica disponível em `http://localhost:4001`.
