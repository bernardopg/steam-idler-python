---
layout: default
title: Steam Idle Bot (PT-BR)
---

## Steam Idle Bot

> 🚀 Automatize o farm de tempo de jogo e drops de cartas Steam sem esforço. Sem mais supervisão manual – apenas configure e deixe rodar! Com recursos inteligentes como detecção de emblemas, suporte Steam Guard e uma configuração Python moderna, é a ferramenta definitiva para entusiastas da Steam.

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/bernardopg/steam-idler-python.svg?style=social)](https://github.com/bernardopg/steam-idler-python/stargazers)

---

## ✨ Por que escolher o Steam Idle Bot?

Cansado de farmar cartas Steam e tempo de jogo manualmente? Este bot lida com tudo de forma inteligente e confiável. Seja para aumentar sua coleção de emblemas ou apenas acumular horas, foi projetado para zero complicações.

- 🎴 **Idle Inteligente de Cartas**: Detecta automaticamente jogos com cartas Steam e pula aqueles que você já farmou completamente (precisa de uma chave Steam Web API para melhores resultados).
- 🕹️ **Sincronização Automática da Biblioteca**: Puxa seus jogos possuídos em tempo real e os rotaciona perfeitamente – sem atualizações manuais necessárias.
- 🔐 **Steam Guard Sem Complicações**: Digite seu código 2FA uma vez e a sessão permanece ativa indefinidamente.
- 🛡️ **Confiabilidade à Prova de Falhas**: Retries integrados, tratamento de erros e logging mantêm tudo funcionando suavemente mesmo com problemas de rede.
- ⚡ **Poder Python Moderno**: Alimentado por UV para configuração ultra-rápida, ambientes reproduzíveis e ferramentas amigáveis para desenvolvimento.
- 📈 **Personalizável e Eficiente**: Ajuste tudo, desde limites de jogos até logging, com suporte para bibliotecas massivas.

Perfeito para gamers, colecionadores ou qualquer pessoa que queira automatizar sua experiência Steam. Junte-se à comunidade e melhore seu perfil sem esforço!

---

## 🚀 Início Rápido (Menos de 5 Minutos)

Comece rapidamente com estes passos simples. Usaremos UV para um ambiente Python sem complicações.

1. **Instale UV** (se você não tiver):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone o Repositório e Instale Dependências**:

   ```bash
   git clone https://github.com/bernardopg/steam-idler-python.git
   cd steam-idler-python
   uv sync
   ```

3. **Configure o Arquivo de Configuração**:

   ```bash
   cp .env.example .env
   # Abra .env no seu editor e adicione seu usuário Steam, senha e chave API (opcional)
   ```

4. **Teste com um Dry Run**:

   ```bash
   ./run.sh --dry-run
   ```

   Isso prevê sua configuração sem fazer login – ótimo para verificações!

5. **Inicie o Bot**:

   ```bash
   ./run.sh
   ```

   Digite seu código Steam Guard se solicitado, e observe funcionando!

> **Dica Pro**: Obtenha uma chave Steam Web API gratuita no [portal de desenvolvedor Steam](https://steamcommunity.com/dev/apikey) para desbloquear recursos avançados como filtro de emblemas. Sem ela, o bot ainda funciona mas faz idle de tudo indiscriminadamente.

---

## 📦 Requisitos

- **Python**: 3.12 ou superior (UV cuida disso para você).
- **Conta Steam**: Com jogos que suportam cartas Steam.
- **Chave Steam Web API** (recomendado): Para sincronização da biblioteca e filtro inteligente.
- **Opcional**: Uma conta Steam dedicada para evitar interromper seu perfil principal.

Sem outras dependências – UV cuida do resto!

---

## ⚙️ Configuração Facilitada

Personalize via `config.py`, variáveis de ambiente ou arquivo `.env`. Variáveis de ambiente sobrescrevem configurações de arquivo para flexibilidade.

| Configuração                  | Descrição                                                                 | Padrão        |
|--------------------------|-----------------------------------------------------------------------------|----------------|
| `USERNAME`, `PASSWORD`   | Suas credenciais de login Steam (obrigatório).                                    | –              |
| `STEAM_API_KEY`          | Desbloqueia busca de biblioteca e verificação de progresso de emblemas.                         | `None`         |
| `GAME_APP_IDS`           | Lista de jogos de fallback se a chave API estiver faltando (ex: [570, 730] para Dota 2/CS:GO). | `[570, 730]`   |
| `FILTER_TRADING_CARDS`   | Apenas fazer idle de jogos com suporte a cartas Steam.                                  | `True`         |
| `FILTER_COMPLETED_CARD_DROPS` | Pular jogos onde todas as cartas já foram dropadas.                               | `True`         |
| `EXCLUDE_APP_IDS`             | Lista manual de app IDs a ignorar sempre.                                         | `[]`           |
| `USE_OWNED_GAMES`        | Buscar automaticamente sua biblioteca completa via API.                                  | `True`         |
| `MAX_GAMES_TO_IDLE`      | Máximo de jogos simultâneos (limite Steam: 32).                                   | `30`           |
| `LOG_LEVEL`, `LOG_FILE`  | Detalhes de logging e saída opcional para arquivo.                                    | `INFO`, `None` |
| `API_TIMEOUT`, `RATE_LIMIT_DELAY` | Timeouts de requisição API e delays para evitar limites de taxa.              | `10`, `0.5`    |

**Exemplos**:

- Variáveis de ambiente: `export STEAM_USERNAME=seunome STEAM_PASSWORD=suasenha`
- Arquivo .env: Crie `.env` com `STEAM_USERNAME=seunome` etc., e UV carrega automaticamente.
- Precisa ignorar um jogo específico? Adicione o ID em `EXCLUDE_APP_IDS`.

---

## ▶️ Executando o Bot

Use o script prático `run.sh` ou chame o pacote diretamente. Aqui está seu kit de ferramentas de comando:

```bash
# Pré-visualizar sem fazer login
./run.sh --dry-run

# Lançamento completo
./run.sh

# Ignorar filtros para teste (idle de tudo)
./run.sh --keep-completed-drops --no-trading-cards

# Limitar a 10 jogos
./run.sh --max-games 10

# Execução direta UV
uv run python -m steam_idle_bot --dry-run
```

### Referência de Flags CLI

| Flag                | Propósito                                                                 |
|---------------------|-------------------------------------------------------------------------|
| `--dry-run`        | Simular e imprimir config/jogos sem interação Steam.              |
| `--no-trading-cards` | Ignorar verificações de cartas e usar a lista bruta de jogos.                          |
| `--keep-completed-drops` | Incluir jogos completamente farmados.                                        |
| `--max-games N`     | Definir máximo de jogos simultâneos.                                               |
| `--config PATH`     | Usar arquivo de configuração personalizado.                                               |
| `--no-cache`        | Desabilitar cache em disco para dados de cartas.                                     |
| `--max-checks N`    | Limitar chamadas API para bibliotecas enormes.                                     |
| `--skip-failures`   | Ignorar silenciosamente erros não-críticos durante verificações.                       |

Combine conforme suas necessidades!

---

## 🧠 Como Funciona (Por Dentro)

1. **Busca de Biblioteca**: Pega seus jogos possuídos via API Steam (ou usa padrões).
2. **Escaneamento de Cartas**: Verifica suporte a cartas Steam e armazena resultados localmente.
3. **Inteligência de Emblemas**: Consulta progresso de emblemas para pular jogos esgotados.
4. **Login Seguro**: Usa o cliente Steam Python oficial com tratamento Steam Guard.
5. **Ciclo de Idle**: Rotaciona jogos a cada 10 minutos em um loop eficiente.

O bot usa sessões HTTP resilientes com retries/backoff. Não é necessário framework assíncrono externo.

---

## 🔐 Segurança e Melhores Práticas

- **Segurança de Credenciais**: `config.py` é ignorado pelo git – mantenha local!
- **Conta Dedicada**: Use um perfil Steam secundário para proteger seu principal.
- **Gerenciamento de Chave API**: Revogue e rotacione se necessário; obtenha sua no [portal de desenvolvedor Steam](https://steamcommunity.com/dev/apikey).
- **Logging**: Use `INFO` para uso normal; aumente para `DEBUG` para troubleshooting.
- **Privacidade**: O bot apenas interage com APIs Steam – nenhum dado sai da sua máquina.

Para vulnerabilidades, veja nossa [Política de Segurança](SECURITY.md).

---

## 🧪 Guia do Desenvolvedor

Contribua para torná-lo ainda melhor! Estrutura do projeto:

```text
steam-idle-bot/
├── config_example.py
├── docs/
│   └── USAGE.md
├── run.sh
├── src/
│   └── steam_idle_bot/
│       ├── __main__.py
│       ├── config/
│       ├── steam/
│       └── utils/
├── tests/
└── uv.lock
```

**Comandos Dev**:

```bash
# Sincronizar dependências dev
uv sync --dev

# Executar testes
uv run pytest

# Lint e formatar
uv run ruff check .
uv run ruff format .

# Checar tipos
uv run mypy src/
```

PRs são bem-vindos! Inclua testes, atualize docs e descreva mudanças.

---

## 🛟 Solução de Problemas

| Problema                          | Solução                                                                 |
|--------------------------------|--------------------------------------------------------------------------|
| Credenciais não configuradas     | Preencha `config.py` ou defina vars de ambiente; evite placeholders.                    |
| Falha no login                   | Verifique credenciais/2FA; cheque por bloqueios de conta.                               |
| Sem jogos para idle               | Adicione chave API ou use `--no-trading-cards`.                                 |
| Erros de import                  | Execute `uv sync`; garanta Python 3.12+.                                       |
| Sem cartas dropando              | Verifique filtros; tente `--keep-completed-drops`.                             |

Para mais, habilite `LOG_LEVEL=DEBUG` e abra uma [issue](https://github.com/bernardopg/steam-idler-python/issues) com logs redigidos.

---

## 📘 Recursos e Comunidade

- [Guia de Uso](USAGE.md)
- [Repositório GitHub](https://github.com/bernardopg/steam-idler-python)
- [Reportar Issues](https://github.com/bernardopg/steam-idler-python/issues)
- Dê estrela no repositório se você gostar! ⭐

---

## ⚖️ Uso Responsável e Licença

Esta ferramenta é para uso educacional e pessoal. Sempre siga os ToS da Steam e leis locais. Não é afiliada à Valve.

Licenciado sob MIT – fork, modifique e aproveite!

---

## Política de Segurança

Veja o arquivo local [SECURITY.md](SECURITY.md) para como reportar vulnerabilidades e versões suportadas.
