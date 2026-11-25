#!/usr/bin/env bash
# Instalador do Assistente Instagram para VPS (Ubuntu/Debian).
# Uso (no terminal da VPS, como root):
#   bash <(curl -fsSL https://raw.githubusercontent.com/tionaza/InstaPy/claude/project-thread-g0qv50/assistente-instagram/instalar.sh)
# Não mexe na aplicação que já roda na VPS: usa pasta, container, rede e porta próprios.
set -euo pipefail

BRANCH="claude/project-thread-g0qv50"
REPO="https://github.com/tionaza/InstaPy.git"
DIR="/opt/assistente-src"
APP="$DIR/assistente-instagram"

[ "$(id -u)" = 0 ] || { echo "Rode como root (digite: sudo -i e tente de novo)."; exit 1; }

echo "==> Instalando dependências (git, curl)..."
command -v git >/dev/null || (apt-get update -qq && apt-get install -y -qq git curl)
if ! command -v docker >/dev/null; then
  echo "==> Instalando Docker..."
  curl -fsSL https://get.docker.com | sh
fi

echo "==> Baixando o sistema..."
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q -B "$BRANCH" FETCH_HEAD
else
  git clone -q -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$APP"

porta_livre() { ! ss -ltn "( sport = :$1 )" | grep -q ":$1"; }

if [ ! -f .env ]; then
  PORTA=8090
  while ! porta_livre "$PORTA"; do PORTA=$((PORTA + 1)); done
  echo
  read -rp "Usuário do Instagram (sem @): " IGU
  read -rsp "Senha do Instagram (não aparece ao digitar): " IGP; echo
  SENHA_PAINEL=$(head -c 300 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-14)
  cp .env.example .env
  sed -i "s/^HOST_PORT=.*/HOST_PORT=$PORTA/" .env
  sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$SENHA_PAINEL/" .env
  sed -i "s/^IG_USERNAME=.*/IG_USERNAME=$IGU/" .env
  # aspas simples evitam que o Docker interprete símbolos como $ na senha
  IGP_ESC=${IGP//\'/\'\"\'\"\'}
  printf '%s\n' "IG_PASSWORD='$IGP_ESC'" > .env.tmp
  grep -v '^IG_PASSWORD=' .env >> .env.tmp && mv .env.tmp .env
  echo "HOST_BIND=0.0.0.0" >> .env
  chmod 600 .env
fi

PORTA=$(grep '^HOST_PORT=' .env | cut -d= -f2)
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "$PORTA"/tcp >/dev/null
fi

echo "==> Subindo o container (pode levar alguns minutos)..."
docker compose up -d --build

IP=$(curl -fsS4 https://api.ipify.org || hostname -I | awk '{print $1}')
echo
echo "============================================================"
echo " Pronto! Abra no navegador:  http://$IP:$PORTA"
echo " Usuário do painel: $(grep '^ADMIN_USER=' .env | cut -d= -f2)"
echo " Senha do painel:   $(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2)"
echo " (guarde a senha; para ver de novo: grep ADMIN_PASSWORD $APP/.env)"
echo " O robô começa em SIMULAÇÃO. Ligue-o na aba 'Robô' do painel."
echo "============================================================"
