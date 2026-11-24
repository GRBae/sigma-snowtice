# 시그마 그래프 API — 어떤 서버/클라우드에서든 이 이미지 하나로 실행
FROM python:3.12-slim
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY api ./api
COPY web ./web
COPY pipeline/graphio.py pipeline/query.py ./pipeline/
COPY data/graph/graph_nodes.jsonl data/graph/graph_edges.jsonl ./data/graph/
ENV TZ=Asia/Seoul PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
