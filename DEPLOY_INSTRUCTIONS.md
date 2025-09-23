# 🚀 Instruções de Deploy - Steam Idle Bot

## ✅ Status do Projeto
- **Site funcionando**: https://idler.bebitterbebetter.com.br/
- **Erro 403 Forbidden**: ✅ RESOLVIDO
- **Workflow GitHub Actions**: ✅ CORRIGIDO

## 🔧 Configuração dos Secrets no GitHub

Para que o deploy automático funcione, configure os seguintes secrets no repositório:

**Acesse:** https://github.com/bernardopg/steam-idler-python/settings/secrets/actions

### Secrets Necessários:
- `SFTP_SERVER`: Servidor FTP (ex: ftp.seudominio.com.br)
- `SFTP_USERNAME`: Usuário do hosting
- `SFTP_PASSWORD`: Senha do hosting
- `SFTP_REMOTE_DIR`: `idler` (para subdomínio)
- `SFTP_PORT`: `21` (para FTP)

## 🎯 Como Fazer Deploy

### Deploy Automático (Recomendado)
1. Faça push para a branch `main`
2. O workflow será executado automaticamente
3. Ou execute manualmente em: Actions → "Deploy site via SFTP" → "Run workflow"

### Deploy Manual (Se necessário)
O deploy automático via GitHub Actions é a forma recomendada. Scripts manuais foram removidos por segurança.

## 📁 Estrutura do Servidor
```
FTP Root/
├── idler/          ← Subdomínio idler.seudominio.com.br
│   ├── index.html
│   ├── assets/
│   └── ...
└── public_html/    ← Domínio principal
    └── ...
```

## 🔍 Resolução de Problemas

### Erro 403 Forbidden
- **Causa**: Arquivo `.htaccess` com configurações problemáticas
- **Solução**: O workflow remove automaticamente arquivos conflitantes

### Caminho Incorreto
- **Problema**: `SFTP_REMOTE_DIR` com valor incorreto
- **Solução**: Use apenas `idler` (não `/public_html/idler`)

### Timeout de Conexão
- **Problema**: Conexão FTP lenta
- **Solução**: O workflow já está configurado com timeout de 60 segundos

## 📝 Arquivos Importantes
- `.github/workflows/deploy-sftp.yml`: Workflow de deploy
- `docs/`: Documentação do projeto (Jekyll)
- `docs/_config.yml`: Configuração do Jekyll

## 🎉 Resultado Final
Após o deploy bem-sucedido, o site estará disponível em:
**https://idler.bebitterbebetter.com.br/**

Com documentação completa em português e inglês, links para o GitHub e design responsivo.
