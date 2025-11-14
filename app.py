from sqlalchemy.orm import relationship 
import pytz
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory 
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import jwt, datetime
from functools import wraps
from flask_cors import CORS
import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import json

# Carrega variáveis de ambiente do arquivo .env (apenas para desenvolvimento local)
load_dotenv()

# CONFIGURAÇÃO OPCIONAL DE S3 (se quiser uploads persistentes em produção)
USE_S3 = bool(os.environ.get('AWS_S3_BUCKET_NAME'))
if USE_S3:
    import boto3
    from botocore.exceptions import ClientError

    AWS_S3_BUCKET_NAME = os.environ.get('AWS_S3_BUCKET_NAME')
    AWS_REGION = os.environ.get('AWS_REGION')
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')

    s3_client = boto3.client(
        's3',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )

    def upload_to_s3(fileobj, key):
        try:
            # fileobj: werkzeug FileStorage -> supports .stream
            s3_client.upload_fileobj(fileobj.stream, AWS_S3_BUCKET_NAME, key)
            return True
        except ClientError as e:
            app.logger.error(f"S3 upload error: {e}")
            return False

    def get_presigned_url(key, expires_in=3600):
        try:
            return s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': AWS_S3_BUCKET_NAME, 'Key': key},
                ExpiresIn=expires_in,
            )
        except ClientError as e:
            app.logger.error(f"S3 presigned URL error: {e}")
            return None

# CONFIGURAÇÕES INICIAIS
app = Flask(__name__)
CORS(app)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chave_super_secreta') # Em produção, defina SECRET_KEY como variável de ambiente
# Permite configurar a URI do banco via variável de ambiente (ex: PostgreSQL em produção)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///banco_local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Desativa o rastreamento de modificações para economizar memória
# Pastas de upload (podem ser configuradas via variáveis de ambiente)
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', os.path.join(app.root_path, 'static', 'uploads'))
app.config['UPLOAD_FOLDER_PERFIL'] = os.environ.get('UPLOAD_FOLDER_PERFIL', os.path.join(app.root_path, 'static', 'uploads', 'perfil'))

db = SQLAlchemy(app) # Inicializa o SQLAlchemy com a aplicação Flask

BRASILIA_TZ = pytz.timezone('America/Sao_Paulo')

# MODELS
class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    senha = db.Column(db.String(150), nullable=False)
    tipo_usuario = db.Column(db.String(50), nullable=False) # 'gerente' ou 'funcionario'
    funcao = db.Column(db.String(100), nullable=True)
    pontos = db.relationship('Ponto', backref='usuario', lazy=True, cascade="all, delete-orphan")
    feedbacks = db.relationship('Feedback', backref='usuario', lazy=True, cascade="all, delete-orphan")
    atestados = db.relationship('Atestado', backref='usuario', lazy=True, cascade="all, delete-orphan")
    dados_adicionais = db.relationship('DadosUsuario', backref='usuario', uselist=False, lazy=True, cascade="all, delete-orphan")
    contabilidade = db.relationship('ContabilidadeFuncionario', backref='funcionario', uselist=False, lazy=True, cascade="all, delete-orphan")

# Modelo para dados adicionais do usuário
class DadosUsuario(db.Model):
    __tablename__ = 'dados_usuario'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    telefone = db.Column(db.String(20), nullable=True)
    nascimento = db.Column(db.Date, nullable=True)
    endereco = db.Column(db.String(255), nullable=True)
    foto_perfil = db.Column(db.String(255), nullable=True, default='default-user.png')

# Modelo para avisos
class Aviso(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    destinatarios = db.Column(db.String(50), nullable=False, default='todos')
    data_envio = db.Column(db.DateTime, default=lambda: datetime.datetime.now(BRASILIA_TZ))

# Modelo para pontos de entrada/saída
class Ponto(db.Model):
    __tablename__ = 'pontos'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    entrada = db.Column(db.DateTime, nullable=False)
    saida = db.Column(db.DateTime)

# Modelo para feedbacks
class Feedback(db.Model):
    __tablename__ = 'feedbacks'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# Modelo para atestados
class Atestado(db.Model):
    __tablename__ = 'atestados'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    motivo = db.Column(db.String(255), nullable=False)
    arquivo = db.Column(db.String(255), nullable=False) # Nome do arquivo no servidor
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(50), default='pendente') # 'pendente', 'aprovado', 'rejeitado'

class FeedbackVisualizado(db.Model):
    __tablename__ = 'feedbacks_visualizados'
    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedbacks.id'), nullable=False)
    visualizado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class AtestadoVisualizado(db.Model):
    __tablename__ = 'atestados_visualizados'
    id = db.Column(db.Integer, primary_key=True)
    atestado_id = db.Column(db.Integer, db.ForeignKey('atestados.id'), nullable=False)
    visualizado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class ContabilidadeFuncionario(db.Model):
    __tablename__ = 'contabilidade_funcionario'
    id = db.Column(db.Integer, primary_key=True) 
    funcionario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), unique=True, nullable=False) # Relação um-para-um com Usuario
    salario_base = db.Column(db.Float, nullable=False, default=0)  # Salário base do funcionário
    tipo_contrato = db.Column(db.String(50), nullable=False, default='CLT') # 'CLT', 'PJ', etc.
    banco = db.Column(db.String(100), nullable=True) # Banco do funcionário
    data_admissao = db.Column(db.String(10), nullable=True) # Formato 'DD/MM/AAAA'
    plano_saude = db.Column(db.Float, default=0) # Novo campo para plano de saúde
    vale_transporte = db.Column(db.Float, default=0) # Novo campo para vale transporte
    vale_refeicao = db.Column(db.Float, default=0) # Novo campo para vale refeição
    bolsa_educacao = db.Column(db.Float, default=0) # Novo campo para bolsa de educação
    historico_pagamentos = db.Column(db.Text, default='[]') # JSON com histórico de pagamentos


# GARANTE QUE OS DIRETÓRIOS DE UPLOAD EXISTEM
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_PERFIL'], exist_ok=True)


#  DECORADOR PARA ROTAS PROTEGIDAS
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers: # Verifica o cabeçalho Authorization
            try:
                token = request.headers['Authorization'].split()[1] # Espera o formato
            except IndexError:
                return jsonify({'message': 'Token malformado'}), 401 # Token malformado
        if not token:
            return jsonify({'message': 'Token está faltando!'}), 401 # Verifica se o token está presente
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"] # Decodifica o token
            )
            current_user = Usuario.query.filter_by(id=data['user_id']).first() # Busca o usuário
            if not current_user:
                return jsonify({'message': 'Usuário do token não encontrado!'}), 401 # Verifica se o usuário existe
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token expirado!'}), 401 # Token expirado
        except jwt.InvalidTokenError: 
            return jsonify({'message': 'Token inválido!'}), 401  # Token inválido
        except Exception as e: # Captura outras exceções para depuração
            return jsonify({'message': f'Erro no token: {str(e)}'}), 401 # Retorna erro genérico
        return f(current_user, *args, **kwargs) # Passa o usuário atual para a função decorada
    return decorated # Retorna a função decorada

# CRIA AS TABELAS NO BANCO DE DADOS
def create_tables():
    with app.app_context():
        app.logger.info('create_tables: starting db.create_all()')
        db.create_all()
        # Adiciona o usuário gerente padrão se não existir
        if not Usuario.query.filter_by(email='gerente@empresa.com').first():
            senha_hash = generate_password_hash('Gerente123!', method='pbkdf2:sha256') # Senha padrão
            gerente = Usuario(nome='Gerente Padrão', email='gerente@empresa.com', senha=senha_hash, tipo_usuario='gerente') # Cria o gerente
            db.session.add(gerente) # Adiciona ao banco
            db.session.commit() # Salva as mudanças
            # Cria os dados adicionais para o gerente
            dados_gerente = DadosUsuario(user_id=gerente.id) # Cria os dados adicionais
            db.session.add(dados_gerente) # Adiciona ao banco
            db.session.commit() # Salva as mudanças
            app.logger.info('create_tables: default manager created')


# Configurações de upload de arquivos (atestados)
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS # Verifica extensões permitidas

# Garante que as tabelas existam quando o módulo for importado (ex: gunicorn)
try:
    app.logger.info('create_tables: import-time call attempting')
    create_tables()
except Exception:
    # Em alguns ambientes (build, ou se DB não estiver disponível) falhar aqui é aceitável;
    # o container/serviço deverá logar o erro e tentar novamente quando o DB estiver pronto.
    app.logger.exception('create_tables: import-time call failed')
    pass


# ROTAS DE AUTENTICAÇÃO
@app.route('/register', methods=['POST']) # ROTA DE REGISTRO
def register(): 
    data = request.get_json() # Obtém os dados JSON da requisição
    if not data or not all(k in data for k in ('nome', 'email', 'senha', 'tipo_usuario')):
        return jsonify({'message': 'Dados insuficientes fornecidos.'}), 400 # Verifica dados obrigatórios
    if Usuario.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'Email já registrado!'}), 400 # Verifica email duplicado

    # PIN exclusivo para gerente
    GERENTE_PIN = '2222' # Pode ser alterado conforme necessário

    if data['tipo_usuario'] == 'gerente': # Registro de gerente requer PIN
        if 'pin' not in data or data['pin'] != GERENTE_PIN: # Verifica o PIN
            return jsonify({'message': 'PIN de gerente inválido!'}), 403 # PIN inválido

    elif data['tipo_usuario'] != 'funcionario': # Apenas 'gerente' ou 'funcionario' são permitidos
        return jsonify({'message': 'Tipo de usuário inválido para registro.'}), 400 # Tipo inválido

    hashed = generate_password_hash(data['senha'], method='pbkdf2:sha256') # Hash da senha
    user = Usuario(nome=data['nome'], email=data['email'], senha=hashed, tipo_usuario=data['tipo_usuario']) # Cria o usuário
    db.session.add(user) # Adiciona ao banco
    db.session.commit() # Salva as mudanças
    # Cria os dados adicionais do usuário
    dados_adicionais = DadosUsuario(user_id=user.id) 
    db.session.add(dados_adicionais)
    db.session.commit()
    return jsonify({'message': 'Usuário registrado com sucesso!'}) # Retorna sucesso

# ROTA DE LOGIN
@app.route('/login', methods=['POST']) 
def login():
    data = request.get_json() # Obtém os dados JSON da requisição
    email = data.get('email') # Pega o email
    senha = data.get('senha') # Pega a senha

    # Verifica se os campos estão preenchidos
    if not email or not senha:
        return jsonify({'message': 'Email e senha são obrigatórios!'}), 400 # Verifica campos obrigatórios
    # Busca o usuário no banco de dados
    user = Usuario.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.senha, senha):
        return jsonify({'message': 'Credenciais inválidas!'}), 401 # Verifica credenciais
    # Gera o token JWT com expiração de 8 horas
    token = jwt.encode({'user_id': user.id, 'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=8)}, app.config['SECRET_KEY'], algorithm="HS256")
    return jsonify({'token': token, 'tipo_usuario': user.tipo_usuario, 'nome_usuario': user.nome}) # Retorna o token e tipo de usuário

# ROTA PROTEGIDA DE DASHBOARD
@app.route('/dashboard', methods=['GET'])
@token_required # Usa o decorador para proteger a rota
def dashboard_api(current_user): 
    return jsonify({
        'nome': current_user.nome, # Nome do usuário
        'tipo_usuario': current_user.tipo_usuario # Exemplo de dado protegido
    }) # Retorna dados do usuário atual


# ROTAS HTML (páginas)
@app.route('/')
def login_page():
    return render_template('login.html') # Página de login

@app.route('/register-page') 
def register_page():
    return render_template('register.html') # Página de registro

@app.route('/dashboard-page')
def dashboard_page():
    return render_template('dashboard.html') # Página do dashboard

@app.route('/meus-pontos-page')
def meus_pontos_page():
    return render_template('meus_pontos.html') # Página de pontos

@app.route('/avisos-page')
def avisos_page():
    return render_template('avisos.html') # Página de avisos

@app.route('/feedback-page')
def feedback_page():
    return render_template('enviar_feedback.html') # Página de feedback

@app.route('/alterar-dados-page')
def alterar_dados_page():
    return render_template('alterar_dados.html') # Página de alteração de dados

@app.route('/adicionar-funcionario')
def adicionar_funcionario_page():
    return render_template('adicionar_funcionarios.html')# Página de adicionar funcionários

@app.route('/relatorios-page')
def relatorios_page():
    return render_template('relatorios.html') # Página de relatórios

@app.route('/gerenciamento-equipe')
def gerenciamento_equipe_page():
    return render_template('gerenciamento_equipe.html') # Página de gerenciamento de equipe

@app.route('/atestados-page')
def atestados_page():
    return render_template('atestados.html') # Página atestados

@app.route('/gerenciar-atestados-page')
def gerenciar_atestados_page():
    return render_template('gerenciar_atestados.html') # Página de gerenciamento de atestados

@app.route('/contabilidade-page')
def contabilidade_page():
    return render_template('contabilidade.html') # Página decontabilidade

@app.route('/editar-contabilidade')
def editar_contabilidade():
    return render_template('editar_contabilidade.html') # Página de edição de contabilidade

# ROTAS DO GERENTE
@app.route('/cadastrar-funcionario', methods=['POST']) # ROTA PARA CADASTRAR FUNCIONÁRIO
@token_required # Protege a rota
def cadastrar_funcionario(current_user):
    if current_user.tipo_usuario != 'gerente': 
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente, pois somente ele tem acesso

    nome = request.form.get('nome') # Pega o nome
    email = request.form.get('email') # Pega o email
    senha = request.form.get('senha') # Pega a senha
    telefone = request.form.get('telefone') # Pega o telefone
    foto = request.files.get('foto_perfil') # Pega a foto de perfil

    # Verifica se os campos obrigatórios estão preenchidos
    if not nome or not email or not senha:
        return jsonify({'message': 'Nome, email e senha são obrigatórios.'}), 400 # Verifica campos obrigatórios
    # Verifica se o email já está cadastrado
    if Usuario.query.filter_by(email=email).first():
        return jsonify({'message': 'E-mail já cadastrado.'}), 400 # Verifica email duplicado

    hashed_password = generate_password_hash(senha) # Hash da senha
    novo_usuario = Usuario(nome=nome, email=email, senha=hashed_password, tipo_usuario='funcionario') # Cria o usuário
    db.session.add(novo_usuario)
    db.session.commit()

    # Dados adicionais (corrigido: user_id)
    dados = DadosUsuario(user_id=novo_usuario.id, telefone=telefone) # Cria os dados adicionais
    if foto:
        filename = secure_filename(foto.filename) # Segurança no nome do arquivo
        foto.save(os.path.join(app.config['UPLOAD_FOLDER_PERFIL'], filename)) # Salva a foto
        dados.foto_perfil = filename # Salva o nome do arquivo no banco
    db.session.add(dados)
    db.session.commit() # Salva as mudanças

    return jsonify({'message': 'Funcionário cadastrado com sucesso!'}) # Retorna sucesso

# ROTA PARA LISTAR FUNCIONÁRIOS
@app.route('/api/funcionarios', methods=['GET'])
@token_required # Protege a rota
def api_listar_funcionarios(current_user):
    if current_user.tipo_usuario != 'gerente': 
        return jsonify({'error': 'Acesso negado'}), 403 # Verifica se é gerente

    funcionarios = Usuario.query.filter_by(tipo_usuario='funcionario').all() # Busca todos os funcionários
    lista = []  # Cria a lista de funcionários
    for f in funcionarios:
        lista.append({
            'id': f.id, # ID do funcionário
            'nome': f.nome, # Adicione outros campos conforme necessário
            'email': f.email # Adicione outros campos conforme necessário
        })
    return jsonify(lista) # Retorna a lista de funcionários

# ROTA PARA EDITAR FUNCIONÁRIO
@app.route('/api/funcionarios/<int:user_id>', methods=['PUT']) 
@token_required
def editar_funcionario(current_user, user_id):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403# Verifica se é gerente
    funcionario = Usuario.query.get(user_id)
    if not funcionario or funcionario.tipo_usuario == 'gerente':
        return jsonify({'message': 'Funcionário não encontrado ou acesso negado para este tipo de usuário'}), 404 # Verifica se o funcionário existe e não é gerente
    
    data = request.get_json() # Obtém os dados JSON da requisição
    if 'nome' in data:
        funcionario.nome = data['nome'] # Atualiza o nome
    if 'email' in data:
        if Usuario.query.filter(Usuario.email == data['email'], Usuario.id != user_id).first():
            return jsonify({'message': 'Email já registrado para outro usuário!'}), 400 # Verifica email duplicado
        funcionario.email = data['email']
    if 'senha' in data and data['senha']:
        funcionario.senha = generate_password_hash(data['senha'], method='pbkdf2:sha256') # Atualiza a senha se fornecida
    if 'funcao' in data:  # <-- ADICIONE ESTA LINHA
        funcionario.funcao = data['funcao'] # Atualiza a função se fornecida
    db.session.commit() # Salva as mudanças
    return jsonify({'message': 'Funcionário atualizado com sucesso!'}) # Retorna sucesso

# ROTA PARA EXCLUIR FUNCIONÁRIO
@app.route('/api/funcionarios/<int:user_id>', methods=['DELETE'])
@token_required
def excluir_funcionario(current_user, user_id): 
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente
    funcionario = Usuario.query.get(user_id) # Busca o funcionário
    if not funcionario or funcionario.tipo_usuario == 'gerente': # Não permite excluir o próprio gerente ou outros gerentes
        return jsonify({'message': 'Funcionário não encontrado ou acesso negado para este tipo de usuário'}), 404 # Verifica se o funcionário existe e não é gerente
    
    # A remoção em cascata é configurada nos relacionamentos do modelo Usuario
    # db.session.delete(funcionario) irá automaticamente deletar DadosUsuario, Ponto, Feedback, Atestado
    db.session.delete(funcionario)
    db.session.commit()
    return jsonify({'message': 'Funcionário excluído com sucesso!'}) # Retorna sucesso

# ROTAS DE PONTO
@app.route('/api/ponto/entrada', methods=['POST'])
@token_required
def registrar_entrada(current_user):
    ultimo_ponto = Ponto.query.filter_by(usuario_id=current_user.id).order_by(Ponto.entrada.desc()).first() # Pega o último ponto
    if ultimo_ponto and not ultimo_ponto.saida: 
        return jsonify({'message': 'Já existe um ponto de entrada registrado sem saída.'}), 400 # Verifica se já existe um ponto aberto
    agora_brasilia = datetime.datetime.now(BRASILIA_TZ)
    novo_ponto = Ponto(usuario_id=current_user.id, entrada=agora_brasilia) # Cria novo ponto
    db.session.add(novo_ponto) # Adiciona ao banco
    db.session.commit()
    return jsonify({'message': 'Entrada registrada com sucesso!', 'entrada': novo_ponto.entrada.isoformat()}) # Retorna sucesso

# ROTA PARA REGISTRAR SAÍDA
@app.route('/api/ponto/saida', methods=['POST'])
@token_required
def registrar_saida(current_user):
    ultimo_ponto = Ponto.query.filter_by(usuario_id=current_user.id).order_by(Ponto.entrada.desc()).first() # Pega o último ponto
    if not ultimo_ponto or ultimo_ponto.saida:
        return jsonify({'message': 'Não há um ponto de entrada aberto para registrar a saída.'}), 400 # Verifica se há um ponto aberto
    agora_brasilia = datetime.datetime.now(BRASILIA_TZ)
    ultimo_ponto.saida = agora_brasilia # Registra a saída
    db.session.commit()
    return jsonify({'message': 'Saída registrada com sucesso!', 'saida': ultimo_ponto.saida.isoformat()}) # Retorna sucessor

# ROTA PARA LISTAR PONTOS DO USUÁRIO ATUAL
@app.route('/api/meus-pontos', methods=['GET'])
@token_required
def meus_pontos(current_user):
    pontos = Ponto.query.filter_by(usuario_id=current_user.id).order_by(Ponto.entrada.desc()).all() # Pega todos os pontos do usuário
    pontos_serializados = [{ # Serializa os pontos
        'id': p.id,
        'entrada': p.entrada.isoformat() if p.entrada else None, # Formata as datas para ISO 8601 
        'saida': p.saida.isoformat() if p.saida else None # Formata as datas para ISO 8601 
    } for p in pontos] # Formata as datas para ISO 8601
    return jsonify(pontos_serializados) # Retorna os pontos serializados

# ROTAS DE AVISOS
@app.route('/api/avisos', methods=['GET'])
@token_required
def listar_avisos(current_user): # Rota para listar avisos
    avisos = Aviso.query.order_by(Aviso.data_envio.desc()).all() # Pega todos os avisos
    avisos_serializados = [{
        'id': a.id, # ID do aviso
        'titulo': a.titulo, # Titúlo do aviso
        'mensagem': a.mensagem, # Mensagem de aviso
        'data_envio': a.data_envio.astimezone(BRASILIA_TZ).isoformat() # Converte para horário de Brasília
    } for a in avisos] # Serializa os avisos
    return jsonify(avisos_serializados) # Retorna os avisos serializados

@app.route('/api/avisos/<int:aviso_id>', methods=['DELETE']) # ROTA PARA EXCLUIR AVISO
@token_required
def excluir_aviso(current_user, aviso_id):
    if current_user.tipo_usuario != 'gerente': 
        return jsonify({'message': 'Acesso negado'}), 403
    aviso = Aviso.query.get(aviso_id)
    if not aviso:
        return jsonify({'message': 'Aviso não encontrado'}), 404
    db.session.delete(aviso)
    db.session.commit()
    return jsonify({'message': 'Aviso excluído com sucesso!'}) 
    
# ROTA PARA PÁGINA DE AVISOS GERAIS
@app.route('/avisos-gerais')
def avisos_gerais():
    return render_template('avisos_gerais.html') # Página de avisos gerais

# Adapte sua rota POST /api/avisos para receber e salvar o campo 'destinatarios'
@app.route('/api/avisos', methods=['POST'])
@token_required
def criar_aviso(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente

    data = request.get_json() # Obtém os dados JSON da requisição
    titulo = data.get('titulo') # Pega o titúlo
    mensagem = data.get('mensagem') # Pega a mensagem
    destinatarios = data.get('destinatarios', 'todos') # Pega os destinatários, padrão 'todos'

    if not titulo or not mensagem:
        return jsonify({'message': 'Título e mensagem são obrigatórios.'}), 400 # Verifica campos obrigatórios

    aviso = Aviso(titulo=titulo, mensagem=mensagem, destinatarios=destinatarios) # Cria o aviso
    db.session.add(aviso)
    db.session.commit() # Salva as mudanças
    return jsonify({'message': 'Aviso publicado com sucesso!'}) # Retorna sucesso

# ROTAS DE FEEDBACK
@app.route('/api/feedback', methods=['POST']) # ROTA PARA ENVIAR FEEDBACK
@token_required
def enviar_feedback(current_user):
    try:
        data = request.get_json()
        if not data or 'mensagem' not in data:
            return jsonify({'message': 'Dados insuficientes fornecidos.'}), 400 # Verifica dados obrigatórios
        # Validação adicional para garantir que a mensagem não esteja vazia ou apenas com espaços
        mensagem = data['mensagem'].strip()
        if not mensagem:
            return jsonify({'message': 'A mensagem não pode estar vazia.'}), 400 # Verifica se a mensagem não está vazia
        # Cria o feedback
        novo_feedback = Feedback(
            usuario_id=current_user.id, # ID do usuário atual
            mensagem=mensagem # Mensagem do feedback
        )
        db.session.add(novo_feedback)
        db.session.commit()
        
        return jsonify({'message': 'Feedback enviado com sucesso!'}), 201 # Retorna sucesso
    # Captura exceções genéricas para evitar falhas silenciosas
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Erro ao enviar feedback: {str(e)}')
        return jsonify({'message': 'Erro interno ao processar feedback'}), 500 # Retorna erro genérico

# ROTA PARA LISTAR FEEDBACKS (SOMENTE GERENTE)
@app.route('/api/feedbacks', methods=['GET'])
@token_required
def listar_feedbacks(current_user): # Rota para listar feedbacks
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente
    feedbacks = db.session.query(Feedback, Usuario.nome).join(Usuario).order_by(Feedback.criado_em.desc()).all() # Pega todos os feedbacks com o nome do usuário
    feedbacks_serializados = [{ # Serializa os feedbacks
        'id': f.id,
        'autor': nome,
        'mensagem': f.mensagem,
        'criado_em': f.criado_em.isoformat(), # Formata as datas para ISO 8601
        'visualizado': FeedbackVisualizado.query.filter_by(feedback_id=f.id).first() is not None
    } for f, nome in feedbacks] 
    return jsonify(feedbacks_serializados) # Retorna os feedbacks serializados

# ROTA PARA MARCAR FEEDBACK COMO VISUALIZADO
@app.route('/api/feedbacks/<int:feedback_id>/visualizar', methods=['PUT'])
@token_required
def marcar_feedback_visualizado(current_user, feedback_id):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    feedback = Feedback.query.get(feedback_id)
    if not feedback:
        return jsonify({'message': 'Feedback não encontrado'}), 404

    if not FeedbackVisualizado.query.filter_by(feedback_id=feedback_id).first():
        visualizacao = FeedbackVisualizado(feedback_id=feedback_id)
        db.session.add(visualizacao)
        db.session.commit()

    return jsonify({'message': 'Feedback marcado como visualizado'})

# ROTAS DE ATESTADOS
@app.route('/api/atestado', methods=['POST']) # ROTA PARA ENVIAR ATESTADO
@token_required
def enviar_atestado(current_user): # Rota para enviar atestado
    if 'file' not in request.files:
        return jsonify({'message': 'Nenhum arquivo enviado'}), 400 # Verifica se o arquivo foi enviado
    file = request.files['file'] # Pega o arquivo
    motivo = request.form.get('motivo') # Pega o motivo
    if file.filename == '' or not motivo:
        return jsonify({'message': 'Arquivo ou motivo não selecionado'}), 400 # Verifica se o arquivo e motivo foram fornecidos
    if file and allowed_file(file.filename):
        # Utiliza o id do usuário para nomear o arquivo e evitar conflitos
        filename = secure_filename(f"atestado_{current_user.id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}") # Nome seguro do arquivo
        if USE_S3:
            key = f"atestados/{filename}"
            success = upload_to_s3(file, key)
            if not success:
                return jsonify({'message': 'Erro ao enviar arquivo para armazenamento'}), 500
            novo_atestado = Atestado(usuario_id=current_user.id, motivo=motivo, arquivo=key) # Salva a chave no banco
        else:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename) # Caminho completo do arquivo
            file.save(filepath)
            novo_atestado = Atestado(usuario_id=current_user.id, motivo=motivo, arquivo=filename) # Cria o atestado

        db.session.add(novo_atestado)
        db.session.commit()
        return jsonify({'message': 'Atestado enviado com sucesso!'}), 201 # Retorna sucesso
    return jsonify({'message': 'Tipo de arquivo não permitido'}), 400 # Tipo de arquivo não permitido

# ROTA PARA LISTAR ATESTADOS (SOMENTE GERENTE)
@app.route('/api/atestados', methods=['GET'])
@token_required
def listar_atestados(current_user): # Rota para listar atestados
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente

    atestados = db.session.query(Atestado, Usuario.nome).join(Usuario).order_by(Atestado.criado_em.desc()).all() # Pega todos os atestados com o nome do usuário
    atestados_serializados = [{ # Serializa os atestados
        'id': a.id,
        'funcionario': nome,
        'motivo': a.motivo,
        'arquivo': a.arquivo,
        'criado_em': a.criado_em.isoformat(), # Formata as datas para ISO 8601
        'status': a.status, # Status do atestado
        'visualizado': AtestadoVisualizado.query.filter_by(atestado_id=a.id).first() is not None
    } for a, nome in atestados] # Serializa os atestados
    return jsonify(atestados_serializados) # Retorna os atestados serializados

# ROTA PARA MARCAR ATESTADO COMO VISUALIZADO
@app.route('/api/atestados/<int:atestado_id>/visualizar', methods=['PUT'])
@token_required
def marcar_atestado_visualizado(current_user, atestado_id):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    atestado = Atestado.query.get(atestado_id)
    if not atestado:
        return jsonify({'message': 'Atestado não encontrado'}), 404

    if not AtestadoVisualizado.query.filter_by(atestado_id=atestado_id).first():
        visualizacao = AtestadoVisualizado(atestado_id=atestado_id)
        db.session.add(visualizacao)
        db.session.commit()

    return jsonify({'message': 'Atestado marcado como visualizado'})

# ROTA PARA GERENCIAR ATESTADO (APROVAR/REJEITAR)
@app.route('/api/atestados/<int:atestado_id>/<status>', methods=['PUT']) # Rota para gerenciar atestado
@token_required
def gerenciar_atestado(current_user, atestado_id, status): # Rota para gerenciar atestado
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente
    atestado = Atestado.query.get(atestado_id)
    if not atestado:
        return jsonify({'message': 'Atestado não encontrado'}), 404 # Verifica se o atestado existe
    if status not in ['aprovado', 'rejeitado']:
        return jsonify({'message': 'Status inválido'}), 400 # Verifica se o status é válido
    atestado.status = status
    db.session.commit()
    return jsonify({'message': f'Atestado {status} com sucesso!'}) # Retorna sucesso

# ROTA PARA LISTAR ATESTADOS DO USUÁRIO ATUAL
@app.route('/api/meus-atestados', methods=['GET']) # Rota para listar atestados do usuário atual
@token_required
def meus_atestados(current_user): # Rota para listar atestados do usuário atual
    atestados = Atestado.query.filter_by(usuario_id=current_user.id).order_by(Atestado.criado_em.desc()).all() # Pega todos os atestados do usuário atual 
    atestados_serializados = [{ # Serializa os atestados
        'id': a.id,
        'motivo': a.motivo,
        'arquivo': a.arquivo,
        'criado_em': a.criado_em.isoformat(),
        'status': a.status
    } for a in atestados] # Serializa os atestados
    return jsonify(atestados_serializados) # Retorna os atestados serializados

# ROTA PARA SERVIR ARQUIVOS DE UPLOAD (atestados e fotos de perfil)
@app.route('/static/uploads/<path:filename>') # ROTA PARA SERVIR ARQUIVOS DE UPLOAD (aceita subpaths)
def uploaded_file(filename):
    # Se estiver usando S3, gera URL pré-assinada para o arquivo
    if USE_S3:
        url = get_presigned_url(filename)
        if url:
            return redirect(url)
        return jsonify({'message': 'Arquivo não encontrado'}), 404

    # Garante que apenas arquivos na pasta UPLOAD_FOLDER podem ser servidos
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename) # Retorna o arquivo solicitado


@app.route('/static/uploads/perfil/<path:filename>') # ROTA PARA SERVIR FOTOS DE PERFIL (aceita subpaths)
def uploaded_profile_picture(filename):
    if USE_S3:
        url = get_presigned_url(filename)
        if url:
            return redirect(url)
        return jsonify({'message': 'Arquivo não encontrado'}), 404

    # Garante que apenas arquivos na pasta UPLOAD_FOLDER_PERFIL podem ser servidos
    return send_from_directory(app.config['UPLOAD_FOLDER_PERFIL'], filename) # Retorna o arquivo solicitado

# ROTAS DE DADOS DO USUÁRIO
@app.route('/api/meus-dados', methods=['GET', 'PUT']) # ROTA PARA VER E EDITAR OS DADOS DO USUÁRIO ATUAL
@token_required
def meus_dados(current_user): # Rota para ver e editar os dados do usuário atual
    if request.method == 'GET': 
        dados = current_user.dados_adicionais # Pega os dados adicionais do usuário
        return jsonify({ # Serializa os dados
            'nome': current_user.nome,
            'email': current_user.email,
            'telefone': dados.telefone if dados else '',
            'nascimento': dados.nascimento.isoformat() if dados and dados.nascimento else '',
            'endereco': dados.endereco if dados else '',
            'foto_perfil': dados.foto_perfil if dados else 'default-user.png'
        }) # Retorna os dados do usuário atual
    
    elif request.method == 'PUT': # Rota para editar os dados do usuário atual
        try:
            data = request.get_json() # Obtém os dados JSON da requisição
            if not data:
                return jsonify({'message': 'Nenhum dado fornecido'}), 400 # Verifica se os dados foram fornecidos

            # Atualiza dados básicos
            if 'nome' in data:
                current_user.nome = data['nome'] # Atualiza o nome
            if 'email' in data:
                if Usuario.query.filter(Usuario.email == data['email'], Usuario.id != current_user.id).first(): # Verifica email duplicado
                    return jsonify({'message': 'Email já está em uso'}), 400 # Verifica email duplicado
                current_user.email = data['email'] # Atualiza o email

            # Garante que os dados adicionais existem
            dados = current_user.dados_adicionais # Pega os dados adicionais
            if not dados:
                dados = DadosUsuario(user_id=current_user.id) # Cria os dados adicionais se não existirem
                db.session.add(dados) # Adiciona ao banco

            # Atualiza campos adicionais
            if 'telefone' in data:
                dados.telefone = data['telefone'] # Atualiza o telefone
            if 'nascimento' in data: # Atualiza a data de nascimento
                try:
                    if data['nascimento']:
                        dados.nascimento = datetime.datetime.strptime(data['nascimento'], '%Y-%m-%d').date() # Atualiza a data de nascimento
                    else:
                        dados.nascimento = None # Permite limpar a data de nascimento
                except ValueError: 
                    return jsonify({'message': 'Formato de data inválido. Use YYYY-MM-DD'}), 400 # Verifica formato de data
            if 'endereco' in data: 
                dados.endereco = data['endereco'] # Atualiza o endereço

            db.session.commit() # Salva as mudanças
            return jsonify({'message': 'Dados atualizados com sucesso!'}) # Retorna sucesso

        except Exception as e: # Captura exceções genéricas para evitar falhas silenciosas
            db.session.rollback() # Reverte a transação em caso de erro
            app.logger.error(f'Erro ao atualizar dados: {str(e)}') # Log para depuração
            return jsonify({'message': 'Erro interno no servidor'}), 500 # Retorna erro genérico
    
# ROTA PARA UPLOAD DE FOTO DE PERFIL
@app.route('/api/upload-foto-perfil', methods=['POST']) 
@token_required
def upload_foto_perfil(current_user): # Rota para upload de foto de perfil
    if 'foto' not in request.files:
        return jsonify({'message': 'Nenhum arquivo de foto enviado'}), 400 # Verifica se o arquivo foi enviado
    
    file = request.files['foto'] # Pega o arquivo
    # Verifica se o arquivo foi selecionado
    if file.filename == '':
        return jsonify({'message': 'Nenhum arquivo selecionado'}), 400 # Verifica se o arquivo foi selecionado
    
    # Verifica o tipo de arquivo
    if not file.mimetype.startswith('image/'): 
        return jsonify({'message': 'O arquivo deve ser uma imagem.'}), 400 # Verifica se o arquivo é uma imagem
    # Salva a foto de perfil
    if file:
        # Gera um nome de arquivo único para a foto de perfil
        filename = secure_filename(f"perfil_{current_user.id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}{os.path.splitext(file.filename)[1]}") # Nome seguro do arquivo
        if USE_S3:
            key = f"perfil/{filename}"
            success = upload_to_s3(file, key)
            if not success:
                return jsonify({'message': 'Erro ao enviar arquivo para armazenamento'}), 500
        else:
            filepath = os.path.join(app.config['UPLOAD_FOLDER_PERFIL'], filename) # Caminho completo do arquivo
            file.save(filepath) # Salva o arquivo

        # Garante que os dados adicionais existem
        dados = DadosUsuario.query.filter_by(user_id=current_user.id).first() # Pega os dados adicionais
        if not dados:
            dados = DadosUsuario(user_id=current_user.id) # Cria os dados adicionais se não existirem
            db.session.add(dados) # Adiciona ao banco

        # Remove a foto antiga se não for a padrão e se existir
        if dados.foto_perfil and dados.foto_perfil != 'default-user.png':
            if USE_S3:
                try:
                    s3_client.delete_object(Bucket=AWS_S3_BUCKET_NAME, Key=dados.foto_perfil)
                except Exception as e:
                    app.logger.error(f"Erro ao remover foto antiga do S3: {e}")
            else:
                old_filepath = os.path.join(app.config['UPLOAD_FOLDER_PERFIL'], dados.foto_perfil) # Caminho da foto antiga
                if os.path.exists(old_filepath): # Verifica se o arquivo existe
                    try:
                        os.remove(old_filepath)
                    except OSError as e:
                        app.logger.error(f"Erro ao remover arquivo antigo: {e}") # Log para depuração

        # Atualiza o nome do arquivo no banco de dados (salva chave S3 ou nome local)
        dados.foto_perfil = key if USE_S3 else filename
        db.session.commit() # Salva as mudanças

        return jsonify({'message': 'Foto de perfil atualizada com sucesso!', 'filename': dados.foto_perfil}), 200 # Retorna sucesso

# ROTA PARA ALTERAR SENHA
@app.route('/api/meus-dados/alterar-senha', methods=['PUT']) 
@token_required
def alterar_senha(current_user): # Rota para alterar a senha do usuário atual
    data = request.get_json()  # Obtém os dados JSON da requisição
    senha_atual = data.get('senha_atual') # Pega a senha atual
    nova_senha = data.get('nova_senha') # Pega a nova senha
    # Verifica se os campos estão preenchidos
    if not senha_atual or not nova_senha:
        return jsonify({'message': 'Preencha todos os campos.'}), 400 # Verifica campos obrigatórios
    # Verifica se a senha atual está correta
    if not check_password_hash(current_user.senha, senha_atual):
        return jsonify({'message': 'Senha atual incorreta.'}), 400 # Verifica se a senha atual está correta
    # Atualiza a senha
    current_user.senha = generate_password_hash(nova_senha) # Hash da nova senha
    db.session.commit()
    return jsonify({'message': 'Senha alterada com sucesso!'}) # Retorna sucesso

# ROTAS DE RELATÓRIOS E GERENCIAMENTO PARA GERENTE
@app.route('/api/gerente/relatorio-pontos', methods=['GET']) # ROTA PARA RELATÓRIO DE PONTOS
@token_required
def relatorio_pontos_gerente(current_user): # Rota para relatório de pontos
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente

    pontos = db.session.query(Ponto, Usuario.nome).join(Usuario).order_by(Ponto.entrada.desc()).all() # Pega todos os pontos com o nome do usuário
    
    pontos_serializados = [{ # Serializa os pontos
        'id': p.id,
        'funcionario': nome,
        'entrada': p.entrada.isoformat() if p.entrada else None,
        'saida': p.saida.isoformat() if p.saida else None
    } for p, nome in pontos] # Serializa os pontos
    
    return jsonify(pontos_serializados) # Retorna os pontos serializados

# ROTA PARA LISTAR FUNCIONÁRIOS COM DADOS ADICIONAIS
@app.route('/api/gerente/funcionarios', methods=['GET']) # ROTA PARA LISTAR FUNCIONÁRIOS
@token_required
def listar_funcionarios_gerente(current_user): # Rota para listar funcionários
    if current_user.tipo_usuario != 'gerente': 
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente

    # Inclui os dados adicionais para exibir telefone e foto de perfil
    funcionarios = db.session.query(Usuario, DadosUsuario).join(DadosUsuario).filter(Usuario.tipo_usuario == 'funcionario').all() # Pega todos os funcionários com dados adicionais
    
    funcionarios_serializados = [{ # Serializa os funcionários
        'id': f.id,
        'nome': f.nome,
        'email': f.email,
        'telefone': d.telefone,
        'foto_perfil': d.foto_perfil,
        'funcao': f.funcao
    } for f, d in funcionarios] # Serializa os funcionários

    return jsonify(funcionarios_serializados) # Retorna os funcionários serializados

# ROTA PARA LISTAR PONTOS DE UM FUNCIONÁRIO ESPECÍFICO
@app.route('/api/gerente/pontos/<int:user_id>', methods=['GET']) 
@token_required
def pontos_por_funcionario(current_user, user_id): # Rota para listar pontos de um funcionário específico
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente
    # Verifica se o funcionário existe e é do tipo 'funcionario'
    funcionario = Usuario.query.get(user_id) # Busca o funcionário
    if not funcionario or funcionario.tipo_usuario != 'funcionario':
        return jsonify({'message': 'Funcionário não encontrado ou não é um funcionário válido'}), 404 # Verifica se o funcionário existe e é do tipo 'funcionario'
    # Busca os pontos do funcionário
    pontos = Ponto.query.filter_by(usuario_id=user_id).order_by(Ponto.entrada.desc()).all() # Pega todos os pontos do funcionário
    pontos_serializados = [{ # Serializa os pontos
        'id': p.id,
        'entrada': p.entrada.isoformat() if p.entrada else None,
        'saida': p.saida.isoformat() if p.saida else None
    } for p in pontos] # Serializa os pontos

    return jsonify({'funcionario_nome': funcionario.nome, 'pontos': pontos_serializados}# Retorna o nome do funcionário e os pontos serializados
    )

# ROTA PARA RELATÓRIO DE PONTOS EM FORMATO CALENDÁRIO
@app.route('/api/gerente/relatorio-pontos-calendario', methods=['GET']) 
@token_required
def relatorio_pontos_calendario(current_user): # Rota para relatório de pontos em formato calendário
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente
    # Obtém os parâmetros de consulta
    month = request.args.get('month', type=int) # Mês
    year = request.args.get('year', type=int) # Ano
    employee_id = request.args.get('employee_id', type=int) # ID do funcionário (opcional)

    # Filtra pontos pelo mês/ano solicitado
    start_date = datetime.datetime(year, month, 1)
    if month == 12: # Se for dezembro, o próximo mês é janeiro do próximo ano
        end_date = datetime.datetime(year + 1, 1, 1) # Próximo ano
    else:
        end_date = datetime.datetime(year, month + 1, 1) # Próximo mês

    query = db.session.query(Ponto, Usuario.nome).join(Usuario) # Consulta inicial
    query = query.filter( # Filtra pela data
        Ponto.entrada >= start_date, # Início do mês 
        Ponto.entrada < end_date # Próximo mês
    ) # Filtra pela data
    # Filtra por funcionário se o ID for fornecido
    if employee_id:
        query = query.filter(Ponto.usuario_id == employee_id)  # Filtra por funcionário se o ID for fornecido

    pontos = query.order_by(Ponto.entrada.asc()).all() # Ordena por data de entrada

    pontos_serializados = [{ # Serializa os pontos
        'id': p.id,
        'funcionario': nome,
        'entrada': p.entrada.isoformat() if p.entrada else None,
        'saida': p.saida.isoformat() if p.saida else None
    } for p, nome in pontos] # Serializa os pontos

    return jsonify(pontos_serializados) # Retorna os pontos serializados

# ROTA PARA LISTAR FEEDBACKS (SOMENTE GERENTE)
@app.route('/api/gerente/feedbacks', methods=['GET']) # ROTA PARA LISTAR FEEDBACKS
@token_required # Protege a rota
def listar_feedbacks_gerente(current_user): # Rota para listar feedbacks
    if current_user.tipo_usuario != 'gerente': 
        return jsonify({'message': 'Acesso negado'}), 403 # Verifica se é gerente
    return listar_feedbacks(current_user)  # Reutiliza a função existente

# ROTA PARA QUE O FUNCIONÁRIO VEJA SUA PRÓPRIA CONTABILIDADE
@app.route('/api/minha-contabilidade', methods=['GET'])
@token_required
def minha_contabilidade(current_user):
    contabilidade = ContabilidadeFuncionario.query.filter_by(funcionario_id=current_user.id).first()
    if not contabilidade:
        # Retorna dados zerados se não houver registro
        return jsonify({
            'id': current_user.id,
            'nome': current_user.nome,
            'funcao': current_user.funcao or '',
            'salario_base': 0,
            'tipo_contrato': '',
            'banco': '',
            'data_admissao': '',
            'plano_saude': 0,
            'vale_transporte': 0,
            'vale_refeicao': 0,
            'bolsa_educacao': 0,
            'historico_pagamentos': []
        })
    
    try:
        historico = json.loads(contabilidade.historico_pagamentos or '[]')
        if not isinstance(historico, list):
            historico = []
    except Exception:
        historico = []
    
    return jsonify({ # Retorna os dados de contabilidade do funcionário
        'id': current_user.id,
        'nome': current_user.nome,
        'funcao': current_user.funcao or '',
        'salario_base': contabilidade.salario_base,
        'tipo_contrato': contabilidade.tipo_contrato,
        'banco': contabilidade.banco,
        'data_admissao': contabilidade.data_admissao,
        'plano_saude': contabilidade.plano_saude,
        'vale_transporte': contabilidade.vale_transporte,
        'vale_refeicao': contabilidade.vale_refeicao,
        'bolsa_educacao': contabilidade.bolsa_educacao,
        'historico_pagamentos': historico
    })

# ROTA PARA GERENCIAR CONTABILIDADE (GERENTE)
@app.route('/api/contabilidade/<int:user_id>', methods=['GET', 'POST'])
@token_required
def contabilidade_funcionario(current_user, user_id):
    funcionario = Usuario.query.get(user_id)
    if not funcionario or funcionario.tipo_usuario != 'funcionario':
        return jsonify({'message': 'Funcionário não encontrado'}), 404

    # Somente gerente pode editar/adicionar
    if request.method == 'POST':
        if current_user.tipo_usuario != 'gerente':
            return jsonify({'message': 'Acesso negado'}), 403

        data = request.get_json()
        contabilidade = ContabilidadeFuncionario.query.filter_by(funcionario_id=user_id).first()
        if not contabilidade:
            contabilidade = ContabilidadeFuncionario(funcionario_id=user_id)
            db.session.add(contabilidade)

        contabilidade.salario_base = data.get('salario_base', 0)
        contabilidade.tipo_contrato = data.get('tipo_contrato', 'CLT')
        contabilidade.banco = data.get('banco', '')
        contabilidade.data_admissao = data.get('data_admissao', '')
        contabilidade.plano_saude = data.get('plano_saude', 0)
        contabilidade.vale_transporte = data.get('vale_transporte', 0)
        contabilidade.vale_refeicao = data.get('vale_refeicao', 0)
        contabilidade.bolsa_educacao = data.get('bolsa_educacao', 0)
        
        historico = data.get('historico_pagamentos', [])
        if not isinstance(historico, list):
            historico = []
        contabilidade.historico_pagamentos = json.dumps(historico)
        
        db.session.commit()
        return jsonify({'message': 'Dados de contabilidade salvos com sucesso!'})

    # GET: gerente pode ver de todos, funcionário só vê o próprio
    if current_user.tipo_usuario == 'funcionario' and current_user.id != user_id:
        return jsonify({'message': 'Acesso negado'}), 403

    contabilidade = ContabilidadeFuncionario.query.filter_by(funcionario_id=user_id).first()
    if not contabilidade:
        # Crie o registro se não existir
        contabilidade = ContabilidadeFuncionario(funcionario_id=user_id)
        db.session.add(contabilidade)
        db.session.commit()
    
    try:
        historico = json.loads(contabilidade.historico_pagamentos or '[]')
        if not isinstance(historico, list):
            historico = []
    except Exception:
        historico = []
    
    dados = {
        'id': funcionario.id,
        'nome': funcionario.nome,
        'funcao': funcionario.funcao or '',
        'salario_base': contabilidade.salario_base,
        'tipo_contrato': contabilidade.tipo_contrato,
        'banco': contabilidade.banco,
        'data_admissao': contabilidade.data_admissao,
        'plano_saude': contabilidade.plano_saude,
        'vale_transporte': contabilidade.vale_transporte,
        'vale_refeicao': contabilidade.vale_refeicao,
        'bolsa_educacao': contabilidade.bolsa_educacao,
        'historico_pagamentos': historico
    }
    return jsonify(dados)

@app.route('/api/funcionarios/<int:user_id>', methods=['GET'])
@token_required
def get_funcionario(current_user, user_id):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403
    funcionario = Usuario.query.get(user_id)
    if not funcionario or funcionario.tipo_usuario == 'gerente':
        return jsonify({'message': 'Funcionário não encontrado ou acesso negado para este tipo de usuário'}), 404
    dados = funcionario.dados_adicionais
    return jsonify({
        'id': funcionario.id,
        'nome': funcionario.nome,
        'email': funcionario.email,
        'funcao': funcionario.funcao,
        'telefone': dados.telefone if dados else '',
        'foto_perfil': dados.foto_perfil if dados else 'default-user.png'
    })

# PONTO DE ENTRADA DA APLICAÇÃO
if __name__ == '__main__':
    create_tables() # Cria as tabelas no banco de dados (para desenvolvimento rápido)
    # Controle de debug via variável de ambiente FLASK_DEBUG (1/true) e porta via PORT
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() in ('1', 'true', 'yes')
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    app.run(host=host, port=port, debug=debug)
