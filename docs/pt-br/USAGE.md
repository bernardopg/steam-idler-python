---
layout: default
title: Guia de Uso (PT-BR)
---

# 📚 Guia de Uso

Sua referência rápida para os comandos do dia a dia do Steam Idle Bot. Para instalação, configuração e arquitetura, veja o [README completo](README.md).

---

## 🔁 Comandos do dia a dia

```bash
# Pré-visualiza config + jogos escolhidos — sem contatar a Steam, sem login
./run.sh --dry-run

# Inicia o idle (terminal). O Steam Guard aparece se necessário (backend python)
./run.sh

# GUI desktop
./run-gui.sh

# Entrada direta do módulo (o run.sh ajusta o PYTHONPATH para você)
uv run python -m steam_idle_bot --dry-run
```

---

## 🕹️ Folha de dicas das flags da CLI

| Flag | O que faz |
| --- | --- |
| `--dry-run` | Pré-visualiza jogos e configurações sem tocar na Steam |
| `--gui` | Abre a GUI desktop (igual a `./run-gui.sh`) |
| `--no-trading-cards` | Pula a detecção de cartas e aceita a lista fornecida |
| `--keep-completed-drops` | Inclui jogos que já esgotaram os drops |
| `--max-games N` | Sobrescreve o máximo de jogos simultâneos |
| `--config PATH` | Carrega configuração de um local personalizado |
| `--no-cache` | Ignora os caches em disco nesta execução |
| `--max-checks N` | Para as buscas de cartas após `N` checagens (bibliotecas grandes) |
| `--skip-failures` | Suprime avisos não-timeout durante as checagens de cartas |

Combine flags conforme a sessão:

```bash
# Faz idle dos dez primeiros jogos, ignorando status de cartas
./run.sh --no-trading-cards --keep-completed-drops --max-games 10

# Reduz chamadas de API para bibliotecas massivas
./run.sh --max-checks 50 --skip-failures

# Dry-run único com credenciais inline
USERNAME=foo PASSWORD=bar ./run.sh --dry-run
```

---

## 📝 Lembretes de configuração

- **Preferido:** copie `.env.example` para `.env` e preencha. **Nunca faça commit do `.env`.**
- **Precedência:** flags da CLI → variáveis de ambiente → `.env` → padrões.
- **Para filtrar drops com precisão** você precisa de uma sessão `web:community` autenticada. O caminho mais fácil: fique logado na Steam no navegador e mantenha `AUTO_BROWSER_COOKIES=true` (o padrão). Veja a [seção de Autenticação](README.md#-autenticação--precisão-dos-drops).
- Um `config.py` legado ainda é lido se existir, mas é desencorajado.

### Variáveis de ambiente úteis

| Variável | Nota rápida |
| --- | --- |
| `STEAM_API_KEY` | Habilita sincronização da biblioteca + dados de emblemas (recomendado) |
| `IDLING_BACKEND` | `python` (Steam Guard / 2FA) ou `steam_utility` |
| `AUTO_BROWSER_COOKIES` | Auto-recupera uma sessão community válida do seu navegador |
| `MAX_GAMES_TO_IDLE` | Limita jogos simultâneos (limite da Steam: 32) |
| `LOG_LEVEL` | `INFO` para saída limpa, `DEBUG` para troubleshooting |

---

## 📚 Mais recursos

- Instalação, arquitetura, autenticação e troubleshooting: [README.md](README.md)
- Política de segurança: [SECURITY.md](SECURITY.md)
