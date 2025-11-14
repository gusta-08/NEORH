// Simula o login do gerente e armazena o token no navegador
function salvarTokenFake() {
    const token = prompt("Cole seu token JWT aqui:");
    localStorage.setItem("token", token);
    alert("Token salvo no localStorage!");
}

<button onclick="salvarTokenFake()">Salvar token manualmente</button>
