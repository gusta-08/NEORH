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

app = Flask(__name__)
CORS(app)

app.config['SECRET_KEY'] = 'chave_super_secreta'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///banco_local.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads' # Pasta geral para uploads (ex: atestados)
app.config['UPLOAD_FOLDER_PERFIL'] = 'static/uploads/perfil' # Pasta específica para fotos de perfil

db = SQLAlchemy(app)

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


class DadosUsuario(db.Model):
    __tablename__ = 'dados_usuario'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    telefone = db.Column(db.String(20), nullable=True)
    nascimento = db.Column(db.Date, nullable=True)
    endereco = db.Column(db.String(255), nullable=True)
    foto_perfil = db.Column(db.String(255), nullable=True, default='default-user.png')


class Aviso(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    destinatarios = db.Column(db.String(50), nullable=False, default='todos')
    data_envio = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Ponto(db.Model):
    __tablename__ = 'pontos'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    entrada = db.Column(db.DateTime, nullable=False)
    saida = db.Column(db.DateTime)


class Feedback(db.Model):
    __tablename__ = 'feedbacks'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class Atestado(db.Model):
    __tablename__ = 'atestados'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    motivo = db.Column(db.String(255), nullable=False)
    arquivo = db.Column(db.String(255), nullable=False) # Nome do arquivo no servidor
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(50), default='pendente') # 'pendente', 'aprovado', 'rejeitado'


# GARANTE QUE OS DIRETÓRIOS DE UPLOAD EXISTEM
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_PERFIL'], exist_ok=True)


# DECORATORS
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            try:
                token = request.headers['Authorization'].split()[1]
            except IndexError:
                return jsonify({'message': 'Token malformado'}), 401
        if not token:
            return jsonify({'message': 'Token está faltando!'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = Usuario.query.filter_by(id=data['user_id']).first()
            if not current_user:
                return jsonify({'message': 'Usuário do token não encontrado!'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token expirado!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Token inválido!'}), 401
        except Exception as e: # Captura outras exceções para depuração
            return jsonify({'message': f'Erro no token: {str(e)}'}), 401
        return f(current_user, *args, **kwargs)
    return decorated


def create_tables():
    with app.app_context():
        db.create_all()
        # Adiciona o usuário gerente padrão se não existir
        if not Usuario.query.filter_by(email='gerente@empresa.com').first():
            senha_hash = generate_password_hash('Gerente123!', method='pbkdf2:sha256')
            gerente = Usuario(nome='Gerente Padrão', email='gerente@empresa.com', senha=senha_hash, tipo_usuario='gerente')
            db.session.add(gerente)
            db.session.commit()
            # Cria os dados adicionais para o gerente
            dados_gerente = DadosUsuario(user_id=gerente.id)
            db.session.add(dados_gerente)
            db.session.commit()

# Configurações de upload de arquivos (atestados)
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ROTAS DE AUTENTICAÇÃO
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data or not all(k in data for k in ('nome', 'email', 'senha', 'tipo_usuario')):
        return jsonify({'message': 'Dados insuficientes fornecidos.'}), 400
    if Usuario.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'Email já registrado!'}), 400

    # PIN exclusivo para gerente
    GERENTE_PIN = '2222'

    if data['tipo_usuario'] == 'gerente':
        if 'pin' not in data or data['pin'] != GERENTE_PIN:
            return jsonify({'message': 'PIN de gerente inválido!'}), 403

    elif data['tipo_usuario'] != 'funcionario':
        return jsonify({'message': 'Tipo de usuário inválido para registro.'}), 400

    hashed = generate_password_hash(data['senha'], method='pbkdf2:sha256')
    user = Usuario(nome=data['nome'], email=data['email'], senha=hashed, tipo_usuario=data['tipo_usuario'])
    db.session.add(user)
    db.session.commit()

    dados_adicionais = DadosUsuario(user_id=user.id)
    db.session.add(dados_adicionais)
    db.session.commit()
    return jsonify({'message': 'Usuário registrado com sucesso!'})


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    senha = data.get('senha')

    if not email or not senha:
        return jsonify({'message': 'Email e senha são obrigatórios!'}), 400

    user = Usuario.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.senha, senha):
        return jsonify({'message': 'Credenciais inválidas!'}), 401
    
    token = jwt.encode({'user_id': user.id, 'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=8)}, app.config['SECRET_KEY'], algorithm="HS256")
    return jsonify({'token': token, 'tipo_usuario': user.tipo_usuario, 'nome_usuario': user.nome})


@app.route('/dashboard', methods=['GET'])
@token_required
def dashboard_api(current_user):
    return jsonify({
        'nome': current_user.nome,
        'tipo_usuario': current_user.tipo_usuario
    })


# ROTAS HTML (páginas)
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login-page')
def login_page():
    return render_template('login.html')

@app.route('/register-page')
def register_page():
    return render_template('register.html')

@app.route('/dashboard-page')
def dashboard_page():
    return render_template('dashboard.html')

@app.route('/meus-pontos-page')
def meus_pontos_page():
    return render_template('meus_pontos.html')

@app.route('/avisos-page')
def avisos_page():
    return render_template('avisos.html')

@app.route('/feedback-page')
def feedback_page():
    return render_template('enviar_feedback.html')

@app.route('/alterar-dados-page')
def alterar_dados_page():
    return render_template('alterar_dados.html')

@app.route('/adicionar-funcionario')
def adicionar_funcionario_page():
    return render_template('adicionar_funcionarios.html')

@app.route('/relatorios-page')
def relatorios_page():
    return render_template('relatorios.html')

@app.route('/gerenciamento-equipe')
def gerenciamento_equipe_page():
    return render_template('gerenciamento_equipe.html')

@app.route('/atestados-page')
def atestados_page():
    return render_template('atestados.html') 

@app.route('/gerenciar-atestados-page')
def gerenciar_atestados_page():
    return render_template('gerenciar_atestados.html') 

@app.route('/contabilidade-page')
def contabilidade_page():
    return render_template('contabilidade.html')

# ROTAS DO GERENTE
@app.route('/cadastrar-funcionario', methods=['POST'])
@token_required
def cadastrar_funcionario(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    nome = request.form.get('nome')
    email = request.form.get('email')
    senha = request.form.get('senha')
    telefone = request.form.get('telefone')
    foto = request.files.get('foto_perfil')

    if not nome or not email or not senha:
        return jsonify({'message': 'Nome, email e senha são obrigatórios.'}), 400

    if Usuario.query.filter_by(email=email).first():
        return jsonify({'message': 'E-mail já cadastrado.'}), 400

    hashed_password = generate_password_hash(senha)
    novo_usuario = Usuario(nome=nome, email=email, senha=hashed_password, tipo_usuario='funcionario')
    db.session.add(novo_usuario)
    db.session.commit()

    # Dados adicionais (corrigido: user_id)
    dados = DadosUsuario(user_id=novo_usuario.id, telefone=telefone)
    if foto:
        filename = secure_filename(foto.filename)
        foto.save(os.path.join(app.config['UPLOAD_FOLDER_PERFIL'], filename))
        dados.foto_perfil = filename
    db.session.add(dados)
    db.session.commit()

    return jsonify({'message': 'Funcionário cadastrado com sucesso!'})

@app.route('/api/funcionarios', methods=['GET'])
@token_required
def api_listar_funcionarios(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'error': 'Acesso negado'}), 403

    funcionarios = Usuario.query.filter_by(tipo_usuario='funcionario').all()
    lista = []
    for f in funcionarios:
        lista.append({
            'id': f.id,
            'nome': f.nome,
            'email': f.email
        })
    return jsonify(lista)

# ROTA PARA EDITAR FUNCIONÁRIO
@app.route('/api/funcionarios/<int:user_id>', methods=['PUT'])
@token_required
def editar_funcionario(current_user, user_id):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403
    funcionario = Usuario.query.get(user_id)
    if not funcionario or funcionario.tipo_usuario == 'gerente':
        return jsonify({'message': 'Funcionário não encontrado ou acesso negado para este tipo de usuário'}), 404
    
    data = request.get_json()
    if 'nome' in data:
        funcionario.nome = data['nome']
    if 'email' in data:
        if Usuario.query.filter(Usuario.email == data['email'], Usuario.id != user_id).first():
            return jsonify({'message': 'Email já registrado para outro usuário!'}), 400
        funcionario.email = data['email']
    if 'senha' in data and data['senha']:
        funcionario.senha = generate_password_hash(data['senha'], method='pbkdf2:sha256')
    if 'funcao' in data:  # <-- ADICIONE ESTA LINHA
        funcionario.funcao = data['funcao']
    db.session.commit()
    return jsonify({'message': 'Funcionário atualizado com sucesso!'})

# ROTA PARA EXCLUIR FUNCIONÁRIO
@app.route('/api/funcionarios/<int:user_id>', methods=['DELETE'])
@token_required
def excluir_funcionario(current_user, user_id):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403
    funcionario = Usuario.query.get(user_id)
    if not funcionario or funcionario.tipo_usuario == 'gerente': # Não permite excluir o próprio gerente ou outros gerentes
        return jsonify({'message': 'Funcionário não encontrado ou acesso negado para este tipo de usuário'}), 404
    
    # A remoção em cascata é configurada nos relacionamentos do modelo Usuario
    # db.session.delete(funcionario) irá automaticamente deletar DadosUsuario, Ponto, Feedback, Atestado
    db.session.delete(funcionario)
    db.session.commit()
    return jsonify({'message': 'Funcionário excluído com sucesso!'})


@app.route('/api/ponto/entrada', methods=['POST'])
@token_required
def registrar_entrada(current_user):
    ultimo_ponto = Ponto.query.filter_by(usuario_id=current_user.id).order_by(Ponto.entrada.desc()).first()
    if ultimo_ponto and not ultimo_ponto.saida:
        return jsonify({'message': 'Já existe um ponto de entrada registrado sem saída.'}), 400
    agora_brasilia = datetime.datetime.now(BRASILIA_TZ)
    novo_ponto = Ponto(usuario_id=current_user.id, entrada=agora_brasilia)
    db.session.add(novo_ponto)
    db.session.commit()
    return jsonify({'message': 'Entrada registrada com sucesso!', 'entrada': novo_ponto.entrada.isoformat()})

@app.route('/api/ponto/saida', methods=['POST'])
@token_required
def registrar_saida(current_user):
    ultimo_ponto = Ponto.query.filter_by(usuario_id=current_user.id).order_by(Ponto.entrada.desc()).first()
    if not ultimo_ponto or ultimo_ponto.saida:
        return jsonify({'message': 'Não há um ponto de entrada aberto para registrar a saída.'}), 400
    agora_brasilia = datetime.datetime.now(BRASILIA_TZ)
    ultimo_ponto.saida = agora_brasilia
    db.session.commit()
    return jsonify({'message': 'Saída registrada com sucesso!', 'saida': ultimo_ponto.saida.isoformat()})

@app.route('/api/meus-pontos', methods=['GET'])
@token_required
def meus_pontos(current_user):
    pontos = Ponto.query.filter_by(usuario_id=current_user.id).order_by(Ponto.entrada.desc()).all()
    pontos_serializados = [{
        'id': p.id,
        'entrada': p.entrada.isoformat() if p.entrada else None,
        'saida': p.saida.isoformat() if p.saida else None
    } for p in pontos]
    return jsonify(pontos_serializados)

# ROTAS DE AVISOS
@app.route('/api/avisos', methods=['GET'])
@token_required
def listar_avisos(current_user):
    avisos = Aviso.query.order_by(Aviso.data_envio.desc()).all()
    avisos_serializados = [{
        'id': a.id,
        'titulo': a.titulo, 
        'mensagem': a.mensagem, 
        'data_envio': a.data_envio.isoformat()
    } for a in avisos]
    return jsonify(avisos_serializados)

@app.route('/avisos-gerais')
def avisos_gerais():
    return render_template('avisos_gerais.html')

# Adapte sua rota POST /api/avisos para receber e salvar o campo 'destinatarios'
@app.route('/api/avisos', methods=['POST'])
@token_required
def criar_aviso(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    data = request.get_json()
    titulo = data.get('titulo')
    mensagem = data.get('mensagem')
    destinatarios = data.get('destinatarios', 'todos')

    if not titulo or not mensagem:
        return jsonify({'message': 'Título e mensagem são obrigatórios.'}), 400

    aviso = Aviso(titulo=titulo, mensagem=mensagem, destinatarios=destinatarios)
    db.session.add(aviso)
    db.session.commit()
    return jsonify({'message': 'Aviso publicado com sucesso!'})

# ROTAS DE FEEDBACK
@app.route('/api/feedback', methods=['POST'])
@token_required
def enviar_feedback(current_user):
    try:
        data = request.get_json()
        if not data or 'mensagem' not in data:
            return jsonify({'message': 'Dados insuficientes fornecidos.'}), 400
        
        mensagem = data['mensagem'].strip()
        if not mensagem:
            return jsonify({'message': 'A mensagem não pode estar vazia.'}), 400

        novo_feedback = Feedback(
            usuario_id=current_user.id,
            mensagem=mensagem
        )
        db.session.add(novo_feedback)
        db.session.commit()
        
        return jsonify({'message': 'Feedback enviado com sucesso!'}), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Erro ao enviar feedback: {str(e)}')
        return jsonify({'message': 'Erro interno ao processar feedback'}), 500

@app.route('/api/feedbacks', methods=['GET'])
@token_required
def listar_feedbacks(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403
    feedbacks = db.session.query(Feedback, Usuario.nome).join(Usuario).order_by(Feedback.criado_em.desc()).all()
    feedbacks_serializados = [{
        'id': f.id,
        'autor': nome,
        'mensagem': f.mensagem,
        'criado_em': f.criado_em.isoformat()
    } for f, nome in feedbacks] 
    return jsonify(feedbacks_serializados)

# ROTAS DE ATESTADOS
@app.route('/api/atestado', methods=['POST'])
@token_required
def enviar_atestado(current_user):
    if 'file' not in request.files:
        return jsonify({'message': 'Nenhum arquivo enviado'}), 400
    file = request.files['file']
    motivo = request.form.get('motivo')
    if file.filename == '' or not motivo:
        return jsonify({'message': 'Arquivo ou motivo não selecionado'}), 400
    if file and allowed_file(file.filename):
        # Utiliza o id do usuário para nomear o arquivo e evitar conflitos
        filename = secure_filename(f"atestado_{current_user.id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        novo_atestado = Atestado(usuario_id=current_user.id, motivo=motivo, arquivo=filename)
        db.session.add(novo_atestado)
        db.session.commit()
        return jsonify({'message': 'Atestado enviado com sucesso!'}), 201
    return jsonify({'message': 'Tipo de arquivo não permitido'}), 400

@app.route('/api/atestados', methods=['GET'])
@token_required
def listar_atestados(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    atestados = db.session.query(Atestado, Usuario.nome).join(Usuario).order_by(Atestado.criado_em.desc()).all()
    atestados_serializados = [{
        'id': a.id,
        'funcionario': nome,
        'motivo': a.motivo,
        'arquivo': a.arquivo,
        'criado_em': a.criado_em.isoformat(),
        'status': a.status
    } for a, nome in atestados]
    return jsonify(atestados_serializados)

@app.route('/api/atestados/<int:atestado_id>/<status>', methods=['PUT'])
@token_required
def gerenciar_atestado(current_user, atestado_id, status):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403
    atestado = Atestado.query.get(atestado_id)
    if not atestado:
        return jsonify({'message': 'Atestado não encontrado'}), 404
    if status not in ['aprovado', 'rejeitado']:
        return jsonify({'message': 'Status inválido'}), 400
    atestado.status = status
    db.session.commit()
    return jsonify({'message': f'Atestado {status} com sucesso!'})

@app.route('/api/meus-atestados', methods=['GET'])
@token_required
def meus_atestados(current_user):
    atestados = Atestado.query.filter_by(usuario_id=current_user.id).order_by(Atestado.criado_em.desc()).all()
    atestados_serializados = [{
        'id': a.id,
        'motivo': a.motivo,
        'arquivo': a.arquivo,
        'criado_em': a.criado_em.isoformat(),
        'status': a.status
    } for a in atestados]
    return jsonify(atestados_serializados)

# ROTA PARA SERVIR ARQUIVOS DE UPLOAD (atestados e fotos de perfil)
@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    # Garante que apenas arquivos na pasta UPLOAD_FOLDER podem ser servidos
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/uploads/perfil/<filename>')
def uploaded_profile_picture(filename):
    # Garante que apenas arquivos na pasta UPLOAD_FOLDER_PERFIL podem ser servidos
    return send_from_directory(app.config['UPLOAD_FOLDER_PERFIL'], filename)


@app.route('/api/meus-dados', methods=['GET', 'PUT'])
@token_required
def meus_dados(current_user):
    if request.method == 'GET':
        dados = current_user.dados_adicionais
        return jsonify({
            'nome': current_user.nome,
            'email': current_user.email,
            'telefone': dados.telefone if dados else '',
            'nascimento': dados.nascimento.isoformat() if dados and dados.nascimento else '',
            'endereco': dados.endereco if dados else '',
            'foto_perfil': dados.foto_perfil if dados else 'default-user.png'
        })
    
    elif request.method == 'PUT':
        try:
            data = request.get_json()
            if not data:
                return jsonify({'message': 'Nenhum dado fornecido'}), 400

            # Atualiza dados básicos
            if 'nome' in data:
                current_user.nome = data['nome']
            if 'email' in data:
                if Usuario.query.filter(Usuario.email == data['email'], Usuario.id != current_user.id).first():
                    return jsonify({'message': 'Email já está em uso'}), 400
                current_user.email = data['email']

            # Garante que os dados adicionais existem
            dados = current_user.dados_adicionais
            if not dados:
                dados = DadosUsuario(user_id=current_user.id)
                db.session.add(dados)

            # Atualiza campos adicionais
            if 'telefone' in data:
                dados.telefone = data['telefone']
            if 'nascimento' in data:
                try:
                    if data['nascimento']:
                        dados.nascimento = datetime.datetime.strptime(data['nascimento'], '%Y-%m-%d').date()
                    else:
                        dados.nascimento = None
                except ValueError:
                    return jsonify({'message': 'Formato de data inválido. Use YYYY-MM-DD'}), 400
            if 'endereco' in data:
                dados.endereco = data['endereco']

            db.session.commit()
            return jsonify({'message': 'Dados atualizados com sucesso!'})

        except Exception as e:
            db.session.rollback()
            app.logger.error(f'Erro ao atualizar dados: {str(e)}')
            return jsonify({'message': 'Erro interno no servidor'}), 500
    
@app.route('/api/upload-foto-perfil', methods=['POST'])
@token_required
def upload_foto_perfil(current_user):
    if 'foto' not in request.files:
        return jsonify({'message': 'Nenhum arquivo de foto enviado'}), 400
    
    file = request.files['foto']
    
    if file.filename == '':
        return jsonify({'message': 'Nenhum arquivo selecionado'}), 400
    
    # Verifica o tipo de arquivo
    if not file.mimetype.startswith('image/'):
        return jsonify({'message': 'O arquivo deve ser uma imagem.'}), 400

    if file:
        # Gera um nome de arquivo único para a foto de perfil
        filename = secure_filename(f"perfil_{current_user.id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}{os.path.splitext(file.filename)[1]}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER_PERFIL'], filename)
        file.save(filepath)
        
        dados = DadosUsuario.query.filter_by(user_id=current_user.id).first()
        if not dados:
            dados = DadosUsuario(user_id=current_user.id)
            db.session.add(dados)
        
        # Remove a foto antiga se não for a padrão e se existir
        if dados.foto_perfil and dados.foto_perfil != 'default-user.png':
            old_filepath = os.path.join(app.config['UPLOAD_FOLDER_PERFIL'], dados.foto_perfil)
            if os.path.exists(old_filepath):
                try:
                    os.remove(old_filepath)
                except OSError as e:
                    print(f"Erro ao remover arquivo antigo: {e}") # Log para depuração
        
        dados.foto_perfil = filename
        db.session.commit()
        
        return jsonify({'message': 'Foto de perfil atualizada com sucesso!', 'filename': filename}), 200


@app.route('/api/meus-dados/alterar-senha', methods=['PUT'])
@token_required
def alterar_senha(current_user):
    data = request.get_json()  # <-- ESSENCIAL!
    senha_atual = data.get('senha_atual')
    nova_senha = data.get('nova_senha')

    if not senha_atual or not nova_senha:
        return jsonify({'message': 'Preencha todos os campos.'}), 400

    if not check_password_hash(current_user.senha, senha_atual):
        return jsonify({'message': 'Senha atual incorreta.'}), 400

    current_user.senha = generate_password_hash(nova_senha)
    db.session.commit()
    return jsonify({'message': 'Senha alterada com sucesso!'})

@app.route('/api/contabilidade', methods=['GET'])
@token_required
def contabilidade(current_user):
    try:
        # Dados fictícios (substitua por dados do banco de dados real)
        dados = {
            'salario_base': 3200.00,
            'abonos': 500.00,
            'descontos': 300.00,
            'horas_extras': 250.00,
            'ferias': 1500.00
        }

        dados['total_liquido'] = (
            dados['salario_base'] +
            dados['abonos'] +
            dados['horas_extras'] +
            dados['ferias'] -
            dados['descontos']
        )

        return jsonify(dados), 200

    except Exception as e:
        app.logger.error(f'Erro ao carregar contabilidade: {e}')
        return jsonify({'message': 'Erro ao buscar informações contábeis.'}), 500

# ROTAS DE RELATÓRIOS E GERENCIAMENTO PARA GERENTE
@app.route('/api/gerente/relatorio-pontos', methods=['GET'])
@token_required
def relatorio_pontos_gerente(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    pontos = db.session.query(Ponto, Usuario.nome).join(Usuario).order_by(Ponto.entrada.desc()).all()
    
    pontos_serializados = [{
        'id': p.id,
        'funcionario': nome,
        'entrada': p.entrada.isoformat() if p.entrada else None,
        'saida': p.saida.isoformat() if p.saida else None
    } for p, nome in pontos]
    
    return jsonify(pontos_serializados)

@app.route('/api/gerente/funcionarios', methods=['GET'])
@token_required
def listar_funcionarios_gerente(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    # Inclui os dados adicionais para exibir telefone e foto de perfil
    funcionarios = db.session.query(Usuario, DadosUsuario).join(DadosUsuario).filter(Usuario.tipo_usuario == 'funcionario').all()
    
    funcionarios_serializados = [{
        'id': f.id,
        'nome': f.nome,
        'email': f.email,
        'telefone': d.telefone,
        'foto_perfil': d.foto_perfil,
        'funcao': f.funcao
    } for f, d in funcionarios]
    
    return jsonify(funcionarios_serializados)

@app.route('/api/gerente/pontos/<int:user_id>', methods=['GET'])
@token_required
def pontos_por_funcionario(current_user, user_id):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    funcionario = Usuario.query.get(user_id)
    if not funcionario or funcionario.tipo_usuario != 'funcionario':
        return jsonify({'message': 'Funcionário não encontrado ou não é um funcionário válido'}), 404

    pontos = Ponto.query.filter_by(usuario_id=user_id).order_by(Ponto.entrada.desc()).all()
    pontos_serializados = [{
        'id': p.id,
        'entrada': p.entrada.isoformat() if p.entrada else None,
        'saida': p.saida.isoformat() if p.saida else None
    } for p in pontos]

    return jsonify({'funcionario_nome': funcionario.nome, 'pontos': pontos_serializados})

@app.route('/api/gerente/relatorio-pontos-calendario', methods=['GET'])
@token_required
def relatorio_pontos_calendario(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403

    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    employee_id = request.args.get('employee_id', type=int)

    # Filtra pontos pelo mês/ano solicitado
    start_date = datetime.datetime(year, month, 1)
    if month == 12:
        end_date = datetime.datetime(year + 1, 1, 1)
    else:
        end_date = datetime.datetime(year, month + 1, 1)

    query = db.session.query(Ponto, Usuario.nome).join(Usuario)
    query = query.filter(
        Ponto.entrada >= start_date,
        Ponto.entrada < end_date
    )
    
    if employee_id:
        query = query.filter(Ponto.usuario_id == employee_id)

    pontos = query.order_by(Ponto.entrada.asc()).all()

    pontos_serializados = [{
        'id': p.id,
        'funcionario': nome,
        'entrada': p.entrada.isoformat() if p.entrada else None,
        'saida': p.saida.isoformat() if p.saida else None
    } for p, nome in pontos]

    return jsonify(pontos_serializados)

@app.route('/api/gerente/feedbacks', methods=['GET'])
@token_required
def listar_feedbacks_gerente(current_user):
    if current_user.tipo_usuario != 'gerente':
        return jsonify({'message': 'Acesso negado'}), 403
    return listar_feedbacks(current_user)

if __name__ == '__main__':
    create_tables()
    app.run(debug=True)

