---
layout: default
title: Política de Segurança (PT-BR)
---

# 🔒 Política de Segurança

## Versões suportadas

O desenvolvimento ativo acontece no branch `main`. Apenas o commit mais recente no `main` recebe atualizações de segurança.

## Reportando uma vulnerabilidade

Por favor, reporte problemas de segurança **de forma privada** via
[GitHub Security Advisories](https://github.com/bernardopg/steam-idler-python/security/advisories/new),
ou por email para `security@steam-idle-bot.local` com:

- uma descrição clara do problema,
- passos para reproduzir, e
- qualquer código de prova de conceito ou logs que demonstrem o impacto (redija os segredos).

Por favor, **não** abra uma issue pública para vulnerabilidades. Nosso objetivo é reconhecer os relatórios em até 5 dias úteis e coordenar com você um cronograma de correção e divulgação.

## Manejo de credenciais & cookies da Steam

Este bot usa credenciais reais da Steam e **cookies de sessão**, que são tão sensíveis quanto senhas. Trate-os adequadamente:

- `.env`, `config.py` e `.cache/` são ignorados pelo git — mantenha-os locais e nunca faça commit.
- **Nunca cole cookies, tokens ou sua chave de API** em issues, logs ou capturas de tela. Ao compartilhar logs para depuração, redija-os.
- O bot só conversa com endpoints oficiais da Steam via HTTPS; nenhum dado é enviado para outro lugar.
- `AUTO_BROWSER_COOKIES` lê cookies apenas do seu navegador local, na sua máquina. Nada é enviado para fora.
- Prefira uma conta Steam dedicada/secundária e rotacione sua chave Web API se suspeitar de exposição.

## Advisories conhecidos / aceitos

A biblioteca `steam[client]` (1.4.x) exige rigidamente `protobuf>=3.0,<4`. Os advisories
de DoS do protobuf **GHSA-8qvm-5x2c-j2w7** e **GHSA-7gcm-g887-7qv7** só têm correção no
protobuf `4.25.8` / `5.29.6`, que essa biblioteca proíbe — então não podem ser resolvidos
sem abandonar o suporte à Steam. São aceitos como **risco tolerável**: o bot só
desserializa protobuf/JSON de servidores Steam autenticados via TLS, então os vetores de
negação de serviço exigem entrada não-confiável que nunca chega até ele. A justificativa
do pin está documentada no `pyproject.toml`.
