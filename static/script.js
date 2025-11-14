// static/script.js

function getToken() {
    const token = localStorage.getItem('jwt_token');
    console.log("DEBUG: getToken() - Token do localStorage:", token ? "Presente" : "Ausente", token);
    return token;
}

function checkUserRole(allowedRoles) {
    const userType = localStorage.getItem('user_type');
    console.log("checkUserRole: userType =", userType, "allowedRoles =", allowedRoles);
    if (!userType) {
        console.error("checkUserRole: userType é nulo ou indefinido. Redirecionando.");
        alert('Erro de autenticação: Tipo de usuário não encontrado. Redirecionando.');
        redirectToLogin();
    } else if (!allowedRoles.includes(userType)) {
        console.error("checkUserRole: Tipo de usuário não permitido. Redirecionando.");
        alert('Acesso negado: Você não tem permissão. Redirecionando.');
        redirectToLogin();
    }
}

function getAuthHeaders() {
    const token = localStorage.getItem('jwt_token');
    return {
        'Authorization': `Bearer ${token}`
    };
}

function redirectToLogin() {
    localStorage.removeItem('jwt_token');
    localStorage.removeItem('user_type');
    localStorage.removeItem('user_name');
    window.location.href = '/';
}

function showMessage(message, type = 'success') {
    const messageDiv = document.getElementById('message-area');
    if (messageDiv) {
        messageDiv.textContent = message;
        messageDiv.className = `alert alert-${type}`;
        messageDiv.style.display = 'block';
        setTimeout(() => {
            messageDiv.style.display = 'none';
        }, 5000);
    } else {
        console.log(`Mensagem (${type}): ${message}`);
        alert(message);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const userNameElement = document.getElementById('user-name-display');
    const userTypeElement = document.getElementById('user-type-display');
    const userType = localStorage.getItem('user_type');
    const userName = localStorage.getItem('user_name');

    if (userNameElement && userName) {
        userNameElement.textContent = userName;
    }
    if (userTypeElement && userType) {
        userTypeElement.textContent = userType.charAt(0).toUpperCase() + userType.slice(1);
    }

    const gerenteLinks = document.querySelectorAll('.gerente-only');
    const funcionarioLinks = document.querySelectorAll('.funcionario-only');

    if (userType === 'gerente') {
        gerenteLinks.forEach(link => link.style.display = 'block');
        funcionarioLinks.forEach(link => link.style.display = 'none');
    } else if (userType === 'funcionario') {
        gerenteLinks.forEach(link => link.style.display = 'none');
        funcionarioLinks.forEach(link => link.style.display = 'block');
    } else {
        gerenteLinks.forEach(link => link.style.display = 'none');
        funcionarioLinks.forEach(link => link.style.display = 'none');
    }

    // Só carrega funcionários se estiver na página de gerenciamento
    if (userType === 'gerente' && window.location.pathname === '/gerenciamento-equipe') {
        carregarFuncionarios();
    }

    // Adiciona proteção e submit para página de adicionar funcionário
    if (userType === 'gerente' && window.location.pathname === '/adicionar-funcionario') {
        checkUserRole(['gerente']);
        const form = document.getElementById('add-employee-form');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();

                const formData = new FormData();
                formData.append('nome', document.getElementById('nome').value);
                formData.append('email', document.getElementById('email').value);
                formData.append('senha', document.getElementById('senha').value);
                formData.append('telefone', document.getElementById('telefone').value);
                const fotoInput = document.getElementById('foto_perfil');
                if (fotoInput && fotoInput.files.length > 0) {
                    formData.append('foto_perfil', fotoInput.files[0]);
                }

                const token = getToken();
                try {
                    const response = await fetch('/cadastrar-funcionario', {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`
                        },
                        body: formData
                    });
                    const data = await response.json();

                    if (response.ok) {
                        showMessage(data.message || 'Funcionário cadastrado com sucesso!', 'success');
                        form.reset();
                    } else {
                        showMessage(data.message || 'Erro ao cadastrar funcionário.', 'danger');
                    }
                } catch (error) {
                    console.error('Erro ao cadastrar funcionário:', error);
                    showMessage('Erro de conexão ao cadastrar funcionário.', 'danger');
                }
            });
        }
    }
});

function carregarFuncionarios() {
    const token = getToken();
    if (!token) {
        showMessage('Token não encontrado. Faça login novamente.', 'danger');
        redirectToLogin();
        return;
    }

    fetch('/api/funcionarios', {
        method: 'GET',
        headers: {
            'Authorization': `Bearer ${token}`
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Erro ao buscar funcionários');
        }
        return response.json();
    })
    .then(data => {
        const lista = document.getElementById('lista-funcionarios');
        if (lista) {
            lista.innerHTML = '';
            data.forEach(funcionario => {
                const li = document.createElement('li');
                li.textContent = `${funcionario.nome} - ${funcionario.email}`;
                lista.appendChild(li);
            });
        }
    })
    .catch(error => {
        showMessage(error.message, 'danger');
    });
}