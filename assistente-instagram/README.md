# Assistente Instagram

Sistema para rodar numa VPS Hostinger **ao lado de uma aplicação que já existe**, sem mexer nela.
Funciona em dois modos, que podem ser usados juntos:

- **Robô (padrão):** entra na sua conta (login e senha) e, sozinho, coleta seguidores de
  concorrentes e autores de posts de hashtags, curte e comenta nos perfis públicos, responde
  comentários nos seus posts e responde Directs recebidos.
- **API oficial (opcional):** webhooks da Meta para respostas instantâneas e radar oficial.

| Função | Como funciona |
|---|---|
| Público-alvo | Seguidores de perfis concorrentes e autores de posts recentes de hashtags |
| Curtir | Até N posts recentes de cada perfil público do público-alvo, com limite diário |
| Comentar no público-alvo | Comentário gerado pela IA com a voz do escritório, ou modelos; com aprovação ou automático |
| Responder comentários nos seus posts | Regras por palavra-chave, resposta padrão ou IA, marcando o @ da pessoa |
| Responder Directs recebidos | Idem; a resposta padrão vai no máximo 1x por dia por conversa |
| Painel web | Robô, fila de aprovação, histórico, regras, público-alvo, configurações |

## Riscos (leia antes de ligar o robô)

1. **Instagram:** o robô usa a API privada do app (biblioteca `instagrapi`), o que viola os Termos de
   Uso. Podem acontecer bloqueios de ação ("Action Blocked"), pedidos de verificação e, em casos
   repetidos, desativação da conta. Login a partir de servidor (IP de datacenter) aumenta as
   verificações.
2. **OAB:** o Código de Ética e o Provimento 205/2021 vedam captação de clientela e mercantilização.
   Por isso os comentários gerados são de conteúdo (sem oferecer serviços nem pedir contato), e o
   robô **não manda Direct para quem nunca falou com o escritório**.

Travas embutidas: limites diários (teto de 150 curtidas e 30 comentários), poucos perfis por ciclo,
intervalos aleatórios entre ações, horário de funcionamento, pausa automática de 24h em qualquer
bloqueio ou verificação, e comentários no público-alvo com aprovação por padrão.

**Aquecimento sugerido:** semana 1 com 30 curtidas e 3 comentários por dia; semana 2 com 60 e 8;
depois no máximo 100 e 15. Se aparecer pausa por bloqueio, volte um degrau.

## Aplicação das skills do projeto

- **voice-builder / post-writer** (`social-media-skills`): o campo *Perfil e voz do escritório* em
  Configurações segue o formato `about-me.md` + `voice.md` dessas skills e vai em toda geração de
  texto pela IA, com a regra delas de nunca inventar fatos, números ou experiências.
- **Instagram Curator** (`agency-agents`): os comentários seguem a linha de "engajamento autêntico
  de comunidade": comentários que acrescentam ao assunto, nada genérico, sem autopromoção.
- Regra comum das skills, "rascunho não autoriza publicar": por isso existe a fila de aprovação.

## 1. Configurar o robô

No `.env` (passo 2): `IG_USERNAME`, `IG_PASSWORD` e, se usar app autenticador, `IG_TOTP_SECRET`.
No painel:
1. **Público-alvo:** cadastre perfis concorrentes (`@perfil`) e hashtags (`direitoprevidenciario`).
2. **Configurações:** preencha *Perfil e voz*, modos de resposta e, se quiser, ligue a IA
   (`ANTHROPIC_API_KEY`).
3. **Robô:** clique em *Conectar conta*. Se o Instagram pedir código, digite e conecte de novo; se
   pedir "Foi você?", confirme no celular. Ajuste os limites, marque *Robô ligado* e salve.
4. Deixe `DRY_RUN=true` no primeiro dia: o robô lê tudo, mas curtidas, comentários e respostas
   saem como "simulado". Confira o histórico e então mude para `false`.

Na primeira execução o robô só marca como vistos os comentários e Directs antigos, para não
responder conversas passadas.

## 1b. (Opcional) API oficial da Meta


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

## Instalação rápida (para leigos)

1. No hPanel da Hostinger, abra **VPS > Gerenciar**. O **IP** da VPS aparece na tela de visão geral
   (algo como `123.45.67.89`). Clique em **Terminal do navegador** (ou "Browser terminal").
2. Cole este comando e aperte Enter:
   ```bash
   bash <(curl -fsSL https://raw.githubusercontent.com/tionaza/InstaPy/claude/project-thread-g0qv50/assistente-instagram/instalar.sh)
   ```
3. Digite o usuário e a senha do Instagram quando ele pedir.
4. No final ele mostra o endereço (ex.: `http://123.45.67.89:8090`), o usuário e a senha do painel.
   Abra esse endereço no navegador.

Se a página não abrir, libere a porta mostrada no **Firewall** da VPS no hPanel (regra TCP de
entrada). Esse acesso por IP não tem cadeado (HTTP); depois vale configurar um subdomínio com HTTPS
(passo 3 abaixo).

## 2. Instalar na VPS sem afetar a aplicação existente (manual)

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

## 4. (Opcional) Ligar o webhook da API oficial

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

- **Robô:** status, conexão, limites, pausa e log de atividade.
- **Fila e histórico:** fila de aprovação (edite o texto antes de enviar) e histórico.
- **Regras:** palavras-chave e respostas, ex.: `aposentadoria, inss` → resposta sobre direito previdenciário.
- **Configurações:** modo automático/aprovação/desligado por canal, respostas padrão, IA opcional.
  Recomendação: comece com **aprovação** e passe para automático só nas regras já testadas.
- **Público-alvo:** cadastre hashtags (`direitodotrabalho`) e perfis concorrentes (`@perfil`, precisa ser conta
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
