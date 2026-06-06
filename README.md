# GitHub Async Growth Bot & Purger

[![GitHub License](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-black.svg)](https://www.python.org/)
[![Tauri Version](https://img.shields.io/badge/tauri-1.6%2B-black.svg)](https://tauri.app/)
[![Next.js Version](https://img.shields.io/badge/next.js-14.1%2B-black.svg)](https://nextjs.org/)

Um motor automatizado assíncrono e persistente de crescimento de engajamento no GitHub. O bot descobre novos repositórios baseando-se em filtros específicos, avalia o código-fonte localmente utilizando Inteligência Artificial (**Ollama** executando localmente sem custos), segue desenvolvedores com alta pontuação técnica e curte (star) repositórios excepcionais. 

Esta versão inclui uma **Interface Gráfica Desktop de Alto Nível** construída em **Next.js, Tailwind CSS e Tauri (Rust)**, um **ciclo de purga (unfollow) assíncrono** inteligente para controle de limites operacionais do GitHub e gerenciamento dinâmico e resiliente de rate limits.

---

## 🏗️ Arquitetura do Projeto

O sistema opera de forma desacoplada em duas camadas principais:

1. **Backend & Script Engine (Python + SQLite)**:
   - Scripts assíncronos independentes e modulares que processam as chamadas à API REST do GitHub e executam Shallow Clones locais para geração de digests textuais do código.
   - Estado persistente salvo em arquivo único SQLite. Nenhuma infraestrutura pesada é necessária.
2. **Desktop Shell (Tauri in Rust + Next.js)**:
   - GUI moderna de alto contraste monocromático (Preto & Branco) estilizada com Tailwind CSS e animada com GSAP.
   - O Tauri Rust spawna o loop do bot Python em background, canaliza e transmite a stream de logs em tempo real para a View de Console, gerencia leitura/escrita segura do `.env`/`whitelist.txt` e executa consultas diretas ao banco SQLite via `rusqlite` para fornecer métricas em tempo real.

---

## 🛠️ Pipeline de Execução

O ciclo sequencial completo do bot compreende as seguintes etapas:

| Módulo/Script | Descrição |
| :--- | :--- |
| **`fetch.py`** | Consulta a API de busca do GitHub por projetos recentes. Filtra e ignora repositórios de usuários já seguidos ou marcados na lista de unfollow. |
| **`evaluate.py`** | Realiza o clone superficial (Shallow Clone) do repositório, constrói um sumário textual dos arquivos e solicita ao **Ollama** notas de `idea` (originalidade) e `skill` (qualidade de engenharia). Limpa os diretórios de clone de forma resiliente a permissões do Windows. |
| **`subscribe.py`** | Segue de forma assíncrona os perfis dos autores cujos repositórios superaram o limiar definido (`SUBSCRIBE_THRESHOLD`). |
| **`star.py`** | Aplica a estrela (star) nos repositórios cujos digests superaram o limiar definido (`STAR_THRESHOLD`). |
| **`unfollow.py`** | Identifica usuários que você segue mas que não te seguem de volta (excluindo uma lista de proteção `whitelist.txt`) e remove a relação. Registra o evento no banco SQLite para evitar segui-los no futuro. |
| **`main.py`** | O orquestrador assíncrono principal que executa o loop das etapas anteriores com jitter dinâmico e controle de periodicidade de purga (executado por padrão a cada 7 dias). |

---

## 💾 Modelagem do Banco de Dados (SQLite)

O banco de dados armazena o histórico em três tabelas integradas:

### Tabela: `entries`
Armazena dados dos repositórios avaliados e flags de engajamento:
- `repo` (TEXT PRIMARY KEY): Nome do repositório no formato `dono/nome`.
- `profile` (TEXT): Nome de usuário do autor.
- `clone_url` (TEXT): URL Git de clonagem.
- `html_url` (TEXT): URL do navegador.
- `followed`/`starred` (INTEGER): Flags booleanas (0 ou 1) que registram ações ativas.
- `idea`/`skill` (REAL): Notas atribuídas pelo modelo de linguagem de 1.0 a 10.0.
- `description` (TEXT): Sumário de uma sentença gerado pela LLM.

### Tabela: `inbound_followers`
Rastreia usuários que sofreram unfollow (purga) para evitar re-follow na etapa de busca:
- `profile` (TEXT PRIMARY KEY): Nome de usuário.
- `unfollowed` (INTEGER): Marcador de remoção (1).
- `updated_at` (TEXT): Data/Hora da última atualização em formato ISO-8601.

### Tabela: `metadata`
Parâmetros chave-valor persistentes do bot:
- `key` (TEXT PRIMARY KEY): Identificador do parâmetro (ex: `last_unfollow_time`).
- `value` (TEXT): Valor associado.

---

## 🚀 Como Instalar e Rodar

### Pré-requisitos
- **Python 3.11+**
- **Node.js (LTS)**
- **Rust Compiler & Cargo** (Necessário para compilar o Tauri wrapper)
- **Git CLI**
- **Ollama** (Rodando localmente com o modelo de código instalado, ex: `qwen2.5-coder:7b`)

### Passo 1: Preparação do Ambiente Python e Dependências
Na raiz do projeto, configure o ambiente virtual Python:
```bash
python3 -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Instale os pacotes necessários (aiohttp e rusqlite já vêm embutidos ou instalados no setup)
pip install aiohttp
```

### Passo 2: Configurando o Ollama
Baixe e inicie o Ollama. Baixe o modelo configurado por padrão:
```bash
ollama pull qwen2.5-coder:7b
```

### Passo 3: Configuração das Variáveis de Ambiente
Copie o template de ambiente `.env` e ajuste as configurações iniciais (essencialmente o seu Token pessoal do GitHub):
```bash
cp env.example .env
```
No arquivo `.env`, preencha as variáveis mandatórias:
* `GITHUB_TOKEN`: Seu Token pessoal de acesso com escopos de `user:follow` e `public_repo`.
* `OLLAMA_URL`: URL do seu Ollama rodando localmente (padrão: `http://localhost:11434`).

### Passo 4: Rodando os Scripts CLI (Alternativa sem Interface)
Você pode executar o pipeline do bot diretamente pelo terminal se não quiser utilizar a interface:
```bash
# Executa apenas uma rodada completa com dry-run (sem aplicar ações reais de escrita)
python main.py --dry-run --force-unfollow

# Executa em loop contínuo assíncrono gravando logs locais
python main.py -i --sleep 600
```

### Passo 5: Rodando a Interface Desktop (Next.js + Tauri)
Navegue para a pasta `gui/` e inicialize a interface de desenvolvimento:
```bash
cd gui
npm install
npm run tauri dev
```
O Tauri abrirá uma janela nativa conectada ao frontend Next.js. O painel compila dinamicamente e você poderá:
1. Iniciar/Parar o loop Python em background.
2. Monitorar os logs em tempo real na View de Terminal.
3. Editar configurações do `.env` diretamente na interface.
4. Adicionar e remover usuários na lista de proteção do `whitelist.txt` sem precisar de editores de texto.

---

## 🧠 Avaliação pela Inteligência Artificial

O Ollama avalia o código de acordo com três âncoras de nota no prompt de sistema:
- **`1.0`**: Código trivial, scripts de estudo ou projetos juniores sem estrutura sólida.
- **`5.0`**: Projetos de complexidade intermediária, bem documentados e estruturados de forma padrão.
- **`9.0`**: Engenharia sênior sólida, frameworks completos, bibliotecas inovadoras e arquitetura complexa.

O bot soma as notas de originalidade da ideia (`idea`) e capacidade técnica mostrada no código (`skill`) em uma escala de `2.0` a `20.0`. Se o projeto superar os valores definidos nas thresholds, o bot age de forma autônoma.

---

## 🛡️ Prevenção de Banimento (Dynamic Rate Limits)
Esta versão descarta sleeps estáticos. O manipulador assíncrono de requisições analisa a API do GitHub dinamicamente. Se a API indicar que os créditos de requisição estão esgotados (`X-RateLimit-Remaining` = 0) ou responder com códigos HTTP `403` ou `429`, o wrapper calcula o timestamp exato do reset (`X-RateLimit-Reset`), executa o sleep de tempo milimétrico e retoma o fluxo de trabalho assim que liberado.
