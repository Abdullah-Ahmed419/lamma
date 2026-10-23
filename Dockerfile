FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND_HOST=0.0.0.0 PORT=8002
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser
COPY server.py manage.py ./
COPY dist ./dist
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import os,urllib.request,urllib.parse; o=os.environ.get('PUBLIC_ORIGIN','http://127.0.0.1:8002'); urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8002/api/health',headers={'Host':urllib.parse.urlsplit(o).netloc}),timeout=3)"
CMD ["python", "server.py"]
