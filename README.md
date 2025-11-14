<<<<<<< HEAD
# NEORH
=======
# Implantação do projeto

Este repositório contém uma aplicação Flask (API + páginas) que gerencia usuários, pontos, atestados e uploads.
Abaixo estão instruções para hospedar de forma fácil e segura usando Render (recomendado).

**Resumo da estratégia recomendada (fácil e segura):**
- Provedor: Render (web service + Postgres gerenciado). Fácil integração com GitHub e SSL automático.
- Banco de dados: PostgreSQL gerenciado (não usar SQLite em produção).
- Uploads: inicialmente em disco local; para produção resiliente, use AWS S3 / DigitalOcean Spaces / Azure Blob Storage.

Pré-requisitos locais
- Python 3.10+ instalado
- Git
- Conta Render (https://render.com)
- (Opcional) Conta AWS para S3 se desejar armazenamento de arquivos persistente

Instalação e teste local
1. Crie e ative um ambiente virtual:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
2. Instale dependências:
```powershell
pip install -r .\requirements.txt
```
3. Crie um arquivo `.env` baseado em `.env.example` (ajuste valores):
- `SECRET_KEY` — chave forte
- `DATABASE_URL` — para desenvolvimento pode permanecer `sqlite:///banco_local.db`
- `FLASK_DEBUG=true`
- `PORT=5000`

4. Execute localmente:
```powershell
python .\app.py
```
Acesse `http://localhost:5000`.

Deploy no Render (passo-a-passo)
1. Suba seu código para um repositório no GitHub (public/privado):
```powershell
git init
git add .
git commit -m "prepare app for render"
# criar repo no GitHub e então:
git remote add origin https://github.com/SEU_USUARIO/SEU_REPO.git
git push -u origin main
```

2. Crie um Web Service no Render:
- No dashboard Render clique em "New" → "Web Service".
- Conecte seu repositório GitHub e escolha a branch `main`.
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn -w 4 -b 0.0.0.0:$PORT "app:app"` (o `Procfile` já está presente, mas você pode usar este comando direto)

3. Configure variáveis de ambiente no painel do serviço (Environment):
- `SECRET_KEY` = sua_chave_secreta
- `DATABASE_URL` = (crie um banco Postgres no Render ou use outro host)
- `FLASK_DEBUG` = `false`
- `UPLOAD_FOLDER` = `/home/render/project/static/uploads`
- `UPLOAD_FOLDER_PERFIL` = `/home/render/project/static/uploads/perfil`

4. Banco de dados PostgreSQL no Render:
- No painel Render clique em "New" → "Postgres Database" e crie uma instância.
- Copie a `DATABASE_URL` gerada e cole nas variáveis de ambiente do Web Service.

5. Deploy automático: ao configurar, Render vai iniciar build e deploy automaticamente. Após concluído, a aplicação estará disponível com HTTPS.

Observações importantes
- Arquivos enviados (uploads) salvos no disco local da instância podem não ser persistentes em alguns provedores ou ao fazer deploys repetidos; para produção resiliente, configure armazenamento em S3/DigitalOcean Spaces/Azure Blob e atualize o código para salvar lá.
- Em produção, defina `FLASK_DEBUG=false` e use uma `SECRET_KEY` forte.
- Considere usar `Flask-Migrate` (Alembic) para migrations ao invés de `create_all()` para gerenciar alterações de schema.

Opções adicionais (posso implementar se desejar)
- Gerar `Dockerfile` e pipeline CI/CD.
- Integrar armazenamento S3 (código + dependências e instruções).
- Adicionar `Flask-Migrate` e scripts de migration.

Próximo passo
- Se concordar, eu configuro integração com S3 ou crio `Dockerfile`. Informe-me qual deseja.

Uso de AWS S3 para uploads (opcional, recomendado para produção)
 - O código agora detecta variáveis de ambiente para AWS S3. Se `AWS_S3_BUCKET_NAME` estiver configurado, uploads serão enviados ao bucket S3 em vez do disco local.
 - O banco salva a chave S3 (ex.: `atestados/atestado_...pdf`) e a aplicação gera URLs pré-assinadas para baixar os arquivos.
 - Para ativar:
	 1. Configure as variáveis de ambiente no Render (ou outro provedor): `AWS_S3_BUCKET_NAME`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
	 2. Crie o bucket no AWS S3 e ajuste permissões (ou deixe privado e use URLs pré-assinadas — o código já usa pre-signed URLs).
	 3. Deploy normalmente; os uploads passarão a ser persistidos no S3.

Se quiser, eu posso também adaptar para DigitalOcean Spaces ou Azure Blob (muda a biblioteca usada e as credenciais). 

Deploy com Docker (alternativa)
- O repositório contém um `Dockerfile` e `entrypoint.sh` que executam as migrations automaticamente (via `run_migrations.py`) e iniciam o `gunicorn`.
- Para rodar localmente com Docker:
```powershell
docker build -t meu-app-flask .
docker run -e PORT=5000 -e FLASK_DEBUG=false -p 5000:5000 --env-file .env meu-app-flask
```

Rodando migrations automaticamente
- O container roda `run_migrations.py` na inicialização (que chama `flask_migrate.upgrade()`). Se preferir rodar migrations manualmente use:
```powershell
# localmente (com FLASK_APP set)
set FLASK_APP=app.py
flask db init      # apenas uma vez
flask db migrate -m "Initial"
flask db upgrade
```

>>>>>>> 0c10c1d (Deploy inicial - código pronto para produção)
