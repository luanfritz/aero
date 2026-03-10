# WhatsApp gratuito com Evolution API

O envio de alertas pode usar a **Evolution API** (gratuita, self-hosted) em vez do Twilio.

## 1. Subir a Evolution API (Docker)

```bash
docker run -d --name evolution-api \
  -p 8080:8080 \
  -e AUTHENTICATION_API_KEY=sua_chave_secreta \
  atendai/evolution-api
```

Documentação oficial: https://doc.evolution-api.com/

## 2. Criar uma instância e conectar seu WhatsApp

1. Acesse `http://localhost:8080` (ou a URL do seu servidor).
2. Crie uma nova instância (ex.: nome `voala`).
3. Gere o QR Code e escaneie com o WhatsApp que será usado para enviar as mensagens (pode ser seu número pessoal ou um número secundário).

## 3. Variáveis de ambiente no projeto

No `.env` ou no ambiente onde roda o `web_app.py` e o `send_whatsapp_alerts.py`:

```env
# Evolution API (gratuita)
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_INSTANCE=voala
EVOLUTION_API_KEY=sua_chave_secreta

# Opcional: dias de ofertas para considerar no envio (padrão 3)
ALERTS_DAYS_RECENT=3
```

Se `EVOLUTION_API_URL` e `EVOLUTION_INSTANCE` estiverem definidos, o sistema usa a Evolution. Caso contrário, tenta o Twilio (se configurado).

## 4. Token de administrador (painel de alertas)

Para acessar `/admin/alertas` e listar/enviar alertas:

```env
ADMIN_TOKEN=um_token_secreto_qualquer
```

No painel, digite esse mesmo token no campo "Token de administrador".

## 5. Disparar alertas

- **Pelo painel:** em `/admin/alertas`, clique em "Enviar alertas agora".
- **Pelo script:** `python send_whatsapp_alerts.py`
- **Por cron:** `curl -X POST -H "X-Admin-Token: SEU_ADMIN_TOKEN" http://localhost:5000/api/admin/send-alerts`
