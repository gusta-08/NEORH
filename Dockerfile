FROM python:3.11-slim
WORKDIR /app

# Instala dependências do sistema necessárias para psycopg2
RUN apt-get update && apt-get install -y build-essential libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p static/uploads static/uploads/perfil
RUN chmod +x ./entrypoint.sh || true

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

ENTRYPOINT ["/bin/sh", "./entrypoint.sh"]
