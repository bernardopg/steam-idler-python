# 🎴 Steam Idle Bot

[![English](https://img.shields.io/badge/lang-English-blue)](docs/en/README.md)
[![Português (BR)](https://img.shields.io/badge/idioma-Portugu%C3%AAs%20(BR)-green)](docs/pt-br/README.md)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/bernardopg/steam-idler-python.svg?style=social)](https://github.com/bernardopg/steam-idler-python/stargazers)

> **EN** — Farm Steam playtime and trading-card drops on autopilot. It syncs your library, idles only the games that still have cards to drop, and remembers what's already finished so every run gets faster. Clean terminal dashboard, optional GUI, two idling backends.
>
> **PT-BR** — Farme tempo de jogo e drops de cartas Steam no automático. Sincroniza sua biblioteca, faz idle só dos jogos que ainda têm cartas para dropar e lembra do que já acabou, deixando cada execução mais rápida. Dashboard limpo no terminal, GUI opcional e dois backends de idle.

---

## 📖 Documentation / Documentação

|                | 🇺🇸 English | 🇧🇷 Português (BR) |
| -------------- | ----------- | ------------------ |
| Full guide     | [README](docs/en/README.md) | [README](docs/pt-br/README.md) |
| Command sheet  | [USAGE](docs/en/USAGE.md)   | [USAGE](docs/pt-br/USAGE.md)   |
| Security       | [SECURITY](docs/en/SECURITY.md) | [SECURITY](docs/pt-br/SECURITY.md) |

---

## ✨ Highlights

- 🎴 **Drops only where it matters** — detects which games have trading cards and how many drops remain, idling just those.
- 🧠 **Learns over time** — a persistent cache records games that are fully farmed and skips them forever, so each run scans less and starts faster.
- 🔐 **Accurate by design** — verifies the Steam web session is genuinely logged in before trusting it, and can auto-recover a valid session from a browser you're signed into.
- 🖥️ **Readable output** — a live terminal panel shows game names, cards remaining, and idle time; a full session report at the end.
- 🔁 **Two backends** — the built-in Python client (Steam Guard / 2FA) or delegation to a local `steam-utility` install, with automatic fallback.
- ⚡ **Modern tooling** — `uv`-managed, reproducible, fully tested.

---

## 🚀 Quick Start

```bash
# 1. Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone and install
git clone https://github.com/bernardopg/steam-idler-python.git
cd steam-idler-python
uv sync

# 3. Configure (never commit the filled .env)
cp .env.example .env
#    then edit .env: USERNAME, PASSWORD, and ideally STEAM_API_KEY

# 4. Preview without contacting Steam
./run.sh --dry-run

# 5. Run it (terminal) — or ./run-gui.sh for the desktop GUI
./run.sh
```

> 💡 A free [Steam Web API key](https://steamcommunity.com/dev/apikey) unlocks automatic library sync and badge-based filtering. Without it the bot still runs, but can't filter as precisely.

---

## 📦 Requirements

- **Python 3.12+** (managed for you by `uv`)
- **A Steam account** with games that have trading cards
- **Steam Web API key** *(recommended)* — library sync + badge data
- **For drop filtering**: an authenticated Steam web session (see the [auth guide](docs/en/README.md#-authentication--card-drop-accuracy))

---

## 🤝 Contributing

Contributions welcome in both languages. See the developer guides:
[🇺🇸 English](docs/en/README.md#-developer-guide) · [🇧🇷 Português](docs/pt-br/README.md#-guia-do-desenvolvedor)

## 📄 License

MIT — see [LICENSE](LICENSE). Not affiliated with Valve. Use responsibly and follow Steam's Terms of Service.
