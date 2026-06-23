---
layout: default
title: Steam Idle Bot (PT-BR)
---

# 🎴 Steam Idle Bot

> Farme tempo de jogo e drops de cartas Steam no automático — com precisão, eficiência e sem supervisão manual.

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/bernardopg/steam-idler-python.svg?style=social)](https://github.com/bernardopg/steam-idler-python/stargazers)

---

## ✨ Por que o Steam Idle Bot?

A maioria dos idlers roda cegamente todos os jogos da biblioteca. Este é **seletivo e preciso**:

- 🎴 **Idle direcionado** — detecta quais jogos têm cartas e quantos drops restam, fazendo idle só desses.
- 🧠 **Mais rápido a cada execução** — um cache persistente registra os jogos já totalmente farmados. Jogo finalizado nunca volta a dropar, então é pulado para sempre. A primeira varredura é a lenta; as próximas são bem mais rápidas.
- 🔐 **Vereditos confiáveis** — antes de confiar numa sessão web da Steam, o bot *verifica se ela está realmente logada*. Uma sessão deslogada/expirada é detectada e reportada, em vez de fazer idle de jogos drenados silenciosamente.
- 🪄 **Autenticação auto-recuperável** — se os cookies configurados não forem uma sessão community válida, ele puxa uma nova de um navegador onde você já está logado na Steam.
- 🖥️ **Saída legível no terminal** — um painel ao vivo com nomes dos jogos, cartas restantes e tempo de idle, além de um relatório completo ao parar.
- 🔁 **Dois backends** — o cliente Steam Python embutido (lida com Steam Guard / 2FA) ou delegação a uma instalação local do `steam-utility`, com fallback automático.
- ⚡ **Moderno e testado** — gerenciado por `uv`, ambientes reproduzíveis, suíte de testes completa e checagem de tipos.

---

## 🚀 Início rápido (menos de 5 minutos)

1. **Instale o [uv](https://docs.astral.sh/uv/)** (se ainda não tiver):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone e instale:**

   ```bash
   git clone https://github.com/bernardopg/steam-idler-python.git
   cd steam-idler-python
   uv sync
   ```

3. **Configure:**

   ```bash
   cp .env.example .env
   # Edite .env — defina USERNAME, PASSWORD e, idealmente, STEAM_API_KEY
   ```

4. **Pré-visualize (sem contatar a Steam):**

   ```bash
   ./run.sh --dry-run
   ```

5. **Execute:**

   ```bash
   ./run.sh          # terminal
   ./run-gui.sh      # GUI desktop (Tkinter)
   ```

   Digite o código Steam Guard se solicitado (apenas no backend Python).

> 💡 **Pegue uma chave de API.** Uma [chave Steam Web API](https://steamcommunity.com/dev/apikey) gratuita habilita a sincronização automática da biblioteca e o filtro por emblemas. Sem ela, o bot usa sua lista manual em `GAME_APP_IDS`.

---

## 📦 Requisitos

- **Python 3.12+** — o `uv` instala e gerencia para você.
- **Uma conta Steam** com jogos que tenham cartas.
- **Chave Steam Web API** *(recomendado)* — para sincronizar a biblioteca e ler progresso de emblemas.
- **Uma sessão web autenticada** *(para filtrar drops)* — veja [Autenticação & precisão dos drops](#-autenticação--precisão-dos-drops).
- *(Opcional)* uma conta Steam dedicada/secundária.

---

## ⚙️ Configuração

As configurações vêm de variáveis de ambiente e do arquivo `.env` (copie o `.env.example`). Precedência: **flags da CLI → variáveis de ambiente → `.env` → padrões**. Um `config.py` legado também é lido se existir, mas o caminho recomendado é o `.env`.

### Principais

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `USERNAME`, `PASSWORD` | Credenciais de login Steam **(obrigatório)**. | – |
| `STEAM_API_KEY` | Habilita sincronização da biblioteca e progresso de emblemas. | _(nenhuma)_ |
| `USE_OWNED_GAMES` | Buscar automaticamente a biblioteca completa via API. | `true` |
| `GAME_APP_IDS` | Lista manual (JSON `[570,730]` ou CSV `570,730`), usada quando não sincroniza a biblioteca. | `[570,730]` |
| `EXCLUDE_APP_IDS` | App IDs a sempre ignorar. | `[]` |
| `MAX_GAMES_TO_IDLE` | Máximo de jogos simultâneos (limite da Steam: 32). | `30` |
| `FILTER_TRADING_CARDS` | Fazer idle só de jogos com cartas. | `true` |
| `FILTER_COMPLETED_CARD_DROPS` | Pular jogos com drops esgotados. | `true` |

### Backend de idle

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `IDLING_BACKEND` | `python` (cliente `steam` embutido) ou `steam_utility` (delega a uma instalação local). | `python` |
| `STEAM_UTILITY_PATH` | Caminho de um checkout local do `steam-utility-multiplataform` (autodescoberto em diretórios irmãos se vazio). | _(auto)_ |

O backend Python lida com Steam Guard / 2FA e constrói uma sessão web autenticada. Se ele falhar ao iniciar, logar, começar ou reconectar, o bot **cai automaticamente** para o backend `steam_utility`.

### Autenticação & cookies

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `STEAM_WEB_COOKIES` | Cookies autenticados para scraping da community. Aceita objeto JSON, array JSON exportado do navegador, ou `k=v; k=v`. | `{}` |
| `AUTO_BROWSER_COOKIES` | Se a sessão configurada não for um login community válido, recupera cookies de um navegador logado localmente. | `true` |
| `BROWSER_COOKIES_BROWSER` | De qual navegador ler: `auto`, `chrome`, `firefox`, `edge`, `brave`, `chromium`, `opera`, `vivaldi`, `librewolf`. | `auto` |

### Caches

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `ENABLE_CARD_CACHE` | Chave mestra para os dois caches em disco. | `true` |
| `CARD_CACHE_PATH` | Cache de "tem cartas". | `.cache/trading_cards.json` |
| `CARD_CACHE_TTL_DAYS` | TTL do cache de cartas. | `30` |
| `DROP_CACHE_PATH` | Cache de "sem drops restantes" (por conta). | `.cache/no_drop_cards.json` |
| `DROP_CACHE_TTL_DAYS` | TTL do cache de sem-drops. | `90` |

### Logging & performance

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Use `INFO` para saída limpa. | `INFO` |
| `LOG_FILE` | Caminho opcional de arquivo de log. | _(nenhum)_ |
| `API_TIMEOUT` | Timeout por requisição (segundos). | `10` |
| `RATE_LIMIT_DELAY` | Delay base entre chamadas; aumenta sozinho em HTTP 429. Suba para bibliotecas enormes. | `1.0` |
| `MAX_CHECKS` | Limita o número de buscas de cartas (ajuste de performance). | _(nenhum)_ |
| `SKIP_FAILURES` | Suprime erros não-timeout durante checagens. | `false` |

---

## 🔐 Autenticação & precisão dos drops

Filtrar os jogos **sem drops restantes** exige ler as páginas autenticadas de emblemas da Steam community. Essa é a parte mais importante de acertar — senão o bot faz idle de jogos que não têm mais nada para dropar.

**O detalhe:** o cookie `steamLoginSecure` é *escopado por audiência*. Um token copiado de `store.steampowered.com` tem audiência `web:store` e é **rejeitado** por `steamcommunity.com` — as páginas carregam deslogadas, todo jogo parece ambíguo e o filtro perde o sentido. Você precisa de um token **`web:community`**.

O bot se defende disso automaticamente:

1. **Verificação de sessão** — antes de confiar em qualquer veredito, ele sonda uma página community para confirmar que você está logado. Se não, registra um aviso claro e fica conservador (exclui os desconhecidos) em vez de fazer idle de jogos drenados.
2. **Recuperação via navegador** — com `AUTO_BROWSER_COOKIES=true` (padrão), ele puxa uma sessão `web:community` válida direto de um navegador onde você está logado na Steam. Como os tokens community são de curta duração, isso mantém o bot auto-recuperável entre execuções.

**Suas opções, da mais simples à mais técnica:**

- ✅ **Fique logado na Steam no navegador** e deixe `AUTO_BROWSER_COOKIES=true`. Nada mais a fazer.
- 🔑 **Use o backend Python** (`IDLING_BACKEND=python`): logar uma vez (com 2FA) gera uma sessão community apropriada.
- 📋 **Cole cookies manualmente** em `STEAM_WEB_COOKIES` — garanta que vieram de `steamcommunity.com`, não da store.

> ℹ️ Se a badge API não retornar `cards_remaining` (comum quando todos os emblemas já estão completos), o bot lê a contagem direto da página de emblemas, para o painel e o relatório continuarem mostrando números reais.

---

## ▶️ Executando o bot

```bash
./run.sh --dry-run                         # pré-visualiza config + jogos, sem contatar a Steam
./run.sh                                   # execução normal (terminal)
./run-gui.sh                               # GUI desktop
./run.sh --max-games 10                    # limita os jogos em idle
./run.sh --no-trading-cards                # pula o filtro de cartas (idle da lista crua)
./run.sh --keep-completed-drops            # inclui jogos já totalmente farmados
uv run python -m steam_idle_bot --dry-run  # entrada direta do módulo
```

### Flags da CLI

| Flag | Propósito |
| --- | --- |
| `--dry-run` | Imprime config e jogos escolhidos sem contatar a Steam. |
| `--gui` | Abre a GUI desktop (igual a `./run-gui.sh`). |
| `--no-trading-cards` | Pula a detecção de cartas; usa a lista crua. |
| `--keep-completed-drops` | Inclui jogos que já esgotaram os drops. |
| `--max-games N` | Sobrescreve o máximo de jogos simultâneos. |
| `--config PATH` | Carrega um arquivo de configuração personalizado. |
| `--no-cache` | Desabilita os caches em disco nesta execução. |
| `--max-checks N` | Limita buscas de cartas (bibliotecas grandes). |
| `--skip-failures` | Suprime avisos não-timeout durante checagens. |

Veja o [Guia de Uso](USAGE.md) para receitas com flags combinadas.

---

## 🧠 Como funciona

```text
jogos possuídos ─▶ tem cartas? ─▶ tem drops restando? ─▶ exclusões ─▶ idle (máx 32)
                    (catálogo de        (badge API ou
                     emblemas +          scraping
                     store API,          autenticado,
                     em cache)           em cache)
```

1. **Biblioteca** — buscada via Steam Web API (com nomes), ou sua lista manual.
2. **Tem cartas** — resolvido pelo catálogo de emblemas, com fallback para a store API; resultados em cache no disco.
3. **Drops restantes** — preferencialmente da badge API; quando faltam dados, cai para scraping autenticado da página da community. Jogos confirmados *sem* drops vão para o cache e são pulados nas próximas execuções.
4. **Loop de idle** — começa o idle e re-roda o pipeline a cada ~10 minutos, reconectando (e trocando de backend) quando preciso. Um painel ao vivo e um relatório de sessão mantêm você informado.

Para um mapa mais profundo da arquitetura, veja o [`CLAUDE.md`](../../CLAUDE.md) na raiz do repositório.

---

## 🖥️ O que você vai ver

Um painel ao vivo durante o idle:

```text
🎮 Steam Idle Bot — em idle agora
┌───┬─────────┬───────────────────────┬──────────────────┬────────────┐
│ # │ App ID  │ Jogo                  │ Cartas restantes │ Tempo idle │
├───┼─────────┼───────────────────────┼──────────────────┼────────────┤
│ 1 │  391540 │ Undertale             │                3 │      0 min │
│ 2 │  362890 │ Black Mesa            │                2 │      0 min │
└───┴─────────┴───────────────────────┴──────────────────┴────────────┘
18 jogos em idle • cartas restantes: 51 • sessão: 0 min
```

> Dica: rode com `LOG_LEVEL=INFO` (o padrão) para essa visão limpa. `DEBUG` adiciona linhas verbosas por jogo, úteis só para troubleshooting.

---

## 🛟 Solução de problemas

| Sintoma | Correção |
| --- | --- |
| `Missing credentials` | Defina `USERNAME`/`PASSWORD` no `.env` (sem valores placeholder). |
| Falha no login | Cheque credenciais/2FA; confirme que a conta não está bloqueada. |
| Aviso "NOT authenticated against steamcommunity" | Sua sessão é store-only/expirada. Fique logado na Steam no navegador (com `AUTO_BROWSER_COOKIES=true`), use `IDLING_BACKEND=python`, ou cole cookies community. Veja [Autenticação](#-autenticação--precisão-dos-drops). |
| Faz idle de jogos drenados / perde os reais | Mesma causa raiz acima — a sessão não é um login community válido. |
| "Cartas restantes" mostra `?` | A badge API não tem `cards_remaining` para um perfil totalmente completo; as contagens são lidas das páginas de emblemas quando a sessão está autenticada. |
| Nenhum jogo para idle | Adicione uma chave de API, ou rode `--no-trading-cards` / `--keep-completed-drops`. |
| Primeira execução lenta | Esperado — varre a biblioteca inteira uma vez e cacheia. As próximas são rápidas. |
| Erros de import | Rode `uv sync`; garanta Python 3.12+. |

Para diagnóstico profundo, defina `LOG_LEVEL=DEBUG` e abra uma [issue](https://github.com/bernardopg/steam-idler-python/issues) com logs **redigidos** (nunca cole cookies, tokens ou sua chave de API).

---

## 🧪 Guia do desenvolvedor

```text
steam-idler-python/
├── .env.example
├── run.sh / run-gui.sh
├── pyproject.toml / uv.lock
├── src/steam_idle_bot/
│   ├── __main__.py        # ponto de entrada
│   ├── main.py            # orquestrador SteamIdleBot
│   ├── gui.py             # GUI Tkinter
│   ├── config/            # settings Pydantic
│   ├── steam/             # backends + serviços de carta/emblema/cookie
│   └── utils/             # logging, tracker, exceções
├── tests/
└── docs/
```

```bash
uv sync --dev                 # instala deps de dev
uv run pytest -q              # roda os testes
uv run pytest -q --cov=src/steam_idle_bot --cov-report=term-missing
uv run ruff check .           # lint
uv run ruff format .          # formata
uv run mypy src               # checagem de tipos
```

A CI roda a suíte em Python 3.12–3.14. PRs são bem-vindos — inclua testes, atualize os docs e descreva suas mudanças. Habilite o guard de pre-commit com `git config core.hooksPath .githooks` (ele bloqueia o commit de `config.py` e arquivos de cache/venv).

---

## 🔒 Segurança

- **Nunca faça commit de segredos.** `.env`, `config.py` e `.cache/` são ignorados pelo git. Mantenha sua chave de API e cookies locais.
- Cookies da Steam são credenciais — trate como senhas.
- Prefira uma conta Steam dedicada/secundária.
- Reporte de vulnerabilidades e notas sobre advisories aceitos: [SECURITY.md](SECURITY.md).

---

## ⚖️ Uso responsável & licença

Para uso educacional e pessoal. Siga os Termos de Serviço da Steam e as leis locais. Não afiliado à Valve. Licenciado sob [MIT](LICENSE).

---

## 📘 Recursos

- [Folha de comandos](USAGE.md) · [Política de segurança](SECURITY.md)
- [Repositório GitHub](https://github.com/bernardopg/steam-idler-python) · [Reportar uma issue](https://github.com/bernardopg/steam-idler-python/issues)
- Curtiu? Deixe uma estrela no repositório ⭐
