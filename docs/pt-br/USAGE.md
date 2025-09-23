# Guia de Uso

Sua referência rápida para comandos diários do Steam Idle Bot. Para uma visão mais profunda, verifique o README principal.

---

## 🔁 Comandos Diários

```bash
# Dry run – imprime configuração, sem login necessário
./run.sh --dry-run

# Iniciar idle (desafio Steam Guard aparecerá se necessário)
./run.sh

# Executar via UV sem o script auxiliar
uv run python -m steam_idle_bot --dry-run
```

---

## 🕹️ Folha de Dicas de Flags CLI

| Flag | O que faz |
| --- | --- |
| `--dry-run` | Pré-visualiza jogos e configurações sem tocar na Steam |
| `--no-trading-cards` | Ignora buscas na loja e aceita a lista de jogos fornecida |
| `--keep-completed-drops` | Inclui jogos que já esgotaram seus drops de emblemas |
| `--max-games N` | Sobrescreve o número máximo de jogos simultâneos |
| `--config PATH` | Carrega configuração de um local personalizado |
| `--no-cache` | Ignora o cache em disco de cartas para esta execução |
| `--max-checks N` | Para buscas na loja após `N` sucessos (bibliotecas grandes) |
| `--skip-failures` | Suprime avisos não-críticos durante verificações de cartas |

Combine flags para adequar à sessão:

```bash
# Ignorar filtros de cartas e fazer idle dos primeiros dez jogos da sua lista
./run.sh --no-trading-cards --keep-completed-drops --max-games 10

# Reduzir chamadas API para bibliotecas massivas
./run.sh --max-checks 50 --skip-failures

# Dry-run único sem tocar em arquivos de configuração
STEAM_USERNAME=foo STEAM_PASSWORD=bar ./run.sh --dry-run
```

---

## 📝 Lembretes de Configuração

- Preferido: copie `.env.example` para `.env` e preencha suas credenciais (não faça commit de `.env`).
- Variáveis de ambiente têm precedência. Use `USERNAME`/`PASSWORD` ou `STEAM_USERNAME`/`STEAM_PASSWORD`. `STEAM_API_KEY` é opcional porém recomendado.
- O `config.py` legado ainda é suportado se presente, mas é desencorajado.

---

## 📚 Mais Recursos

- Instalação, arquitetura e troubleshooting: veja [README.md](README.md).
