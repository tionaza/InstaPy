# Assistente Instagram (API oficial da Meta)

Sistema para rodar numa VPS Hostinger **ao lado de uma aplicação que já existe**, sem mexer nela.
Ele recebe os comentários e Directs da sua conta pelos webhooks oficiais da Meta e responde
automaticamente (ou depois da sua aprovação), além de um **Radar** que acompanha hashtags e
concorrentes para você interagir com esse público.

| Função | Como funciona |
|---|---|
| Responder comentários nas suas publicações | Automático ou com aprovação, por regras de palavra-chave, resposta padrão ou IA |
| Responder Directs recebidos | Idem, dentro da janela de 24h da Meta; não repete a resposta padrão na mesma conversa |
| Direct para quem comentou | Opcional (resposta privada oficial, 1 por comentário) |
| Radar de hashtags | Lista publicações recentes da hashtag com sugestão de comentário para você interagir pelo app |
| Radar de concorrentes | Seguidores, posts e engajamento médio de perfis comerciais concorrentes, e as publicações deles |
| Painel web | Fila de aprovação, histórico, regras, configurações, com usuário e senha |

## Por que não curte/comenta/manda Direct sozinho para desconhecidos

1. **Instagram:** robôs não oficiais (como o InstaPy deste repositório) violam os Termos de Uso, e a
   Meta bloqueia ou desativa as contas com frequência. A API oficial não permite curtir, nem
   comentar ou mandar Direct a quem não falou com você primeiro.
2. **OAB:** o Código de Ética e o Provimento 205/2021 proíbem a captação de clientela e o envio
   de mensagens não solicitadas em massa. Responder quem procurou o escritório é permitido; abordar
   ativamente seguidores de concorrentes não é.

Por isso o Radar entrega o público e a sugestão, e **você** interage manualmente, com naturalidade.

## 1. Preparar a Meta (uma vez)

1. A conta do Instagram precisa ser **Profissional (Empresa ou Criador)** e estar ligada a uma
   **Página do Facebook**.
2. Em <https://developers.facebook.com/apps> crie um app do tipo **Empresa**.
3. Adicione os produtos **Instagram** (configuração com *Login do Facebook para Empresas*) e **Webhooks**.
4. Gere um token da Página com as permissões: `instagram_basic`, `instagram_manage_comments`,
   `instagram_manage_messages`, `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`,
   `business_management`. Converta em **token de longa duração** (Ferramentas > Depurador de token >
   Estender). Anote:
   - `FB_PAGE_ID` (ID da Página) e `IG_USER_ID` (ID da conta Instagram Business, em
     `GET /{page-id}?fields=instagram_business_account`);
   - `PAGE_ACCESS_TOKEN`; `META_APP_SECRET` (Configurações > Básico > Chave secreta).
5. No Instagram do celular: Configurações > Mensagens > **Permitir acesso a mensagens** (ferramentas conectadas).
6. Para responder pessoas que não são administradoras do app, envie o app para **Análise do App** pedindo
   *Acesso Avançado* nas permissões acima. Até lá, teste com contas que tenham papel no app.

O webhook será configurado no passo 4, quando o endereço HTTPS já estiver no ar.

## 2. Instalar na VPS sem afetar a aplicação existente

Acesse por SSH (`ssh root@IP_DA_VPS`, IP no hPanel da Hostinger).

```bash
# Docker (pule se `docker compose version` já funcionar)
curl -fsSL https://get.docker.com | sh

# Escolha uma porta livre. Veja o que está em uso:
sudo ss -ltnp | grep -E ':(80|443|8090)\b'

# Baixe o projeto numa pasta própria
cd /opt
git clone -b claude/project-thread-g0qv50 https://github.com/tionaza/InstaPy.git assistente-src
cd assistente-src/assistente-instagram
cp .env.example .env
nano .env    # preencha senha do painel, dados da Meta, um WEBHOOK_VERIFY_TOKEN inventado

docker compose up -d --build
curl http://127.0.0.1:8090/health      # deve responder {"ok":true,...}
```

O container tem nome, rede e volume próprios, limite de 256 MB de RAM e meia CPU, e escuta só em
`127.0.0.1:8090`. Ele não usa as portas 80/443, então a aplicação atual continua igual.

## 3. Publicar com HTTPS num subdomínio

Crie no DNS (hPanel > Domínios > DNS) um registro **A** `insta` apontando para o IP da VPS.
Depois descubra quem já atende as portas 80/443 (`sudo ss -ltnp | grep -E ':(80|443)\b'`):

**Nginx** (mais comum):
```bash
sudo cp deploy/nginx-assistente.conf /etc/nginx/sites-available/assistente-instagram
sudo nano /etc/nginx/sites-available/assistente-instagram   # ajuste o server_name
sudo ln -s /etc/nginx/sites-available/assistente-instagram /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx                 # nginx -t protege o site atual
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d insta.seudominio.com.br
```

**Caddy:** acrescente ao Caddyfile
`insta.seudominio.com.br { reverse_proxy 127.0.0.1:8090 }` e rode `sudo systemctl reload caddy`.

**Traefik / Easypanel / Coolify / Docker Manager da Hostinger:** crie um domínio/serviço apontando
para `http://IP_INTERNO:8090` pelo painel da ferramenta, ou conecte o container à rede do proxy e
adicione as labels dela. Se tiver dúvida, envie a saída do `ss -ltnp` e de `docker ps` que eu ajusto.

## 4. Ligar o webhook

No app da Meta > Webhooks > objeto **Instagram**:
- URL de callback: `https://insta.seudominio.com.br/webhook`
- Token de verificação: o mesmo `WEBHOOK_VERIFY_TOKEN` do `.env`
- Assine os campos **comments** e **messages**.

Depois assine a Página no app (uma vez):
```bash
curl -X POST "https://graph.facebook.com/v21.0/$FB_PAGE_ID/subscribed_apps?subscribed_fields=feed&access_token=$PAGE_ACCESS_TOKEN"
```

Comente numa publicação sua e mande um Direct de outra conta: os itens aparecem no painel
(`https://insta.seudominio.com.br`). Com tudo certo, mude `DRY_RUN=false` no `.env` e rode
`docker compose up -d`.

## Uso do painel

- **Respostas:** fila de aprovação (edite o texto antes de enviar) e histórico.
- **Regras:** palavras-chave e respostas, ex.: `aposentadoria, inss` → resposta sobre direito previdenciário.
- **Configurações:** modo automático/aprovação/desligado por canal, respostas padrão, IA opcional.
  Recomendação: comece com **aprovação** e passe para automático só nas regras já testadas.
- **Radar:** cadastre hashtags (`direitodotrabalho`) e perfis concorrentes (`@perfil`, precisa ser conta
  comercial ou de criador). Clique em "Abrir no Instagram", interaja pelo app e marque "Já interagi".

## Manutenção

```bash
cd /opt/assistente-src/assistente-instagram
git pull && docker compose up -d --build        # atualizar
docker compose logs -f --tail=100               # ver logs
docker compose down                             # parar (dados ficam no volume)
docker run --rm -v assistente-instagram_assistente_dados:/d -v $PWD:/b alpine cp /d/assistente.db /b/backup.db   # backup
```

O token de longa duração da Página não expira enquanto o app estiver ativo, mas se você trocar a
senha do Facebook gere outro e atualize o `.env`.

## Desenvolvimento

```bash
pip install -r requirements.txt pytest
DB_PATH=./dev.db ADMIN_PASSWORD=x uvicorn app.main:app --reload
pytest -q tests
```
