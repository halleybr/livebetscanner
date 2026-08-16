# ⚡ LIVE BET SCANNER — Radar de Jogos Ao Vivo

Sistema simples que monitora os **jogos de futebol ao vivo** do RoboBet.app,
complementa com estatísticas ao vivo do **SokkerPRO** (m2.sokkerpro.com) e
calcula o **LIVE PRESSURE SCORE (0–100)** para mostrar somente as partidas com
ritmo elevado (LPS ≥ 70) e potencial para **gols** e/ou **escanteios**.

## Como rodar

Requisitos: **Python 3.9+** (apenas a biblioteca padrão — nada para instalar).

```bash
python server.py
```

Abra **http://localhost:8765**. Pronto.

### Configuração (variáveis de ambiente)

| Variável         | Padrão | Descrição                                   |
|------------------|--------|---------------------------------------------|
| `PORT`           | `8765` | Porta do servidor                           |
| `POLL_SECONDS`   | `30`   | Frequência de atualização do RoboBet        |
| `ENRICH_SECONDS` | `60`   | Frequência do enriquecimento SokkerPRO      |
| `STATS_ENABLED`  | `1`    | `0` desliga a busca de estatísticas         |
| `TOP_N`          | `10`   | Máximo de jogos exibidos                    |
| `MIN_LPS`        | `70`   | Filtro mínimo do Live Pressure Score        |
| `TELEGRAM_BOT_TOKEN` | — | Token do bot para alertas (opcional)    |
| `TELEGRAM_CHAT_ID`   | — | Chat/grupo que recebe os alertas (opcional) |

Exemplo: `MIN_LPS=60 python server.py` (mostra também jogos "OBSERVAR").

## GitHub Pages (site estático)

O GitHub Pages não roda o backend Python, então o site estático usa o
**GitHub Actions** para gerar os dados: o workflow `.github/workflows/pages.yml`
roda o scanner (`python build.py`), grava o JSON no mesmo formato da rota
`/api/scanner` e publica tudo em `https://<usuário>.github.io/livebetscanner/`.

* O workflow roda em cada push para `main`, manualmente (aba *Actions* →
  *Deploy GitHub Pages* → *Run workflow*) e por cron nativo como *backup*
  (duas expressões deslocadas — **mas o cron do GitHub é best-effort**: pode
  atrasar minutos ou não disparar; observamos isso em 15/08/2026).
* **Para atualização confiável a cada ~2 min**, use um agendador externo
  gratuito (cron-job.org) que chama o `workflow_dispatch` — veja o passo a
  passo em [`CRON-EXTERNO.md`](CRON-EXTERNO.md).
* **Latência esperada no Pages:** sem o agendador externo, os dados podem ficar
  vários minutos velhos. O frontend mostra a idade em tempo real no topo
  ("Última atualização: há X min") e a destaca em laranja quando passa de 10 min.
* O frontend consome `api/scanner.json` (com cache-buster `?t=` para o CDN do
  Pages); no servidor local ele cai na API ao vivo (`/api/scanner`) normalmente.
* **Histórico de entradas:** o registro green/red fica em `data/entries.json` e
  é commitado de volta ao repositório pelo próprio workflow a cada execução
  (permissão `contents: write`), para sobreviver entre os builds do Pages.

## 📋 Possíveis entradas (histórico green/red)

Toda **dica recomendada** pelo radar (partida que entrou na lista de
oportunidades, LPS ≥ mínimo, com mercado ativo) é registrada na seção
"Possíveis entradas" do site. O registro **não é apagado** quando a pressão cai:

* ⏳ **ATIVA** — o jogo ainda está rolando (ou a dica ainda não deu resultado).
* 🟢 **GREEN** — o jogo terminou e a dica deu certo (placar final confirma).
* 🔴 **RED** — o jogo terminou e a dica deu errado.
* ⚪ **SEM DADO** — jogo terminou, mas não dá para avaliar (ex.: escanteios,
  pois a fonte pública não expõe escanteio final).

Avaliação com o placar final do RoboBet (`status == finished`): **Over 0.5 gol**
→ green se total ≥ 1; **Over 1.5 gols** → green se total ≥ 2; **Próximo gol**
→ green se houve gol depois da entrada. O histórico mostrado cobre as últimas
**24 horas** (o ledger guarda 48h).
* Se a fonte externa falhar no momento da geração, o site continua no ar e
  mostra o status de erro na barra de fontes (nada quebra).

> Obs.: o Pages é configurado com a fonte **GitHub Actions** (em *Settings* →
> *Pages* → *Build and deployment* → *Source* → *GitHub Actions*).

## 🤖 Alertas no Telegram

O scanner envia **2 tipos de alerta** no Telegram (opcional — sem configuração
nada é enviado e nada quebra):

1. **🎯 Nova entrada** — quando o radar recomenda uma dica (LPS ≥ mínimo, com
   mercado ativo): mercado, partida, liga, LPS, minuto, odd e probabilidade.
   Dispara tanto quando a partida **entra na lista** pela primeira vez quanto
   quando ela **reaparece** depois de ter saído (com cooldown de 15 min por
   partida para não repetir o mesmo aviso a cada ciclo).
2. **✅/❌ Liquidação** — quando a partida termina e a dica fecha em **GREEN**,
   **RED** ou **SEM DADO** (escanteios), com o placar final.

### Criar o bot (uma vez)

1. No Telegram, abra o **@BotFather** → `/newbot` → escolha um nome e um
   username. Copie o **token** (formato `123456:ABC...`).
2. Abra uma conversa com o seu bot (ou crie um grupo e adicione-o) e mande
   qualquer mensagem para ele.
3. Descubra o **chat id**: abra no navegador
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → procure o número em
   `message.chat.id` (grupos usam ids negativos).

### Ativar

* **Local:** `export TELEGRAM_BOT_TOKEN=<token> TELEGRAM_CHAT_ID=<chat_id>`
  antes de `python server.py` (ou `build.py`).
* **GitHub Pages:** em *Settings* → *Secrets and variables* → *Actions*, crie
  os secrets **`TELEGRAM_BOT_TOKEN`** e **`TELEGRAM_CHAT_ID`** com os mesmos
  valores. O workflow `pages.yml` já os repassa ao `build.py` — a cada execução
  (~2 min), novas entradas e liquidações são avisadas automaticamente.
* Opcional: `TELEGRAM_SITE_URL` para trocar o link incluído nas mensagens.

Dica: para testar sem esperar um jogo, rode `python build.py` com as variáveis
setadas — se houver entrada nova ou liquidação pendente, o alerta sai na hora.

## Arquitetura e fluxo dos dados

```
RoboBet (API pública) ──► server.py ──► LIVE PRESSURE SCORE ──► API JSON ──► Frontend (página única)
  m.robobet.app/api/        poll 30s     /api/scanner                  poll 30s
  events/today                        ▲
SokkerPRO (estatísticas) ─────────────┘
  m2.sokkerpro.com/livescores          (1 chamada por ciclo, 60s)
```

1. **Poll do RoboBet** (a cada 30 s): o endpoint público `m.robobet.app/api/events/today`
   devolve todas as partidas do dia. Ficam apenas as **ao vivo** (minuto, período,
   placar, odds, bandeiras `hasFire`/`hasBall`/`justScored`, cartões) e as
   **probabilidades do modelo** da própria plataforma: over 0.5/1.5/2.5 gols,
   BTTS, escanteios esperados (total e janela de 10 min) e a sugestão
   (`best_suggestion`) com mercado/probabilidade/odd.
2. **Enriquecimento SokkerPRO** (a cada 60 s): `GET m2.sokkerpro.com/livescores`
   devolve, em **uma única chamada**, as estatísticas ao vivo de todas as
   partidas: xG, finalizações (total/no gol/fora/área), escanteios, posse,
   ataques e ataques perigosos, barra de pressão (0–100), ataques perigosos
   por minuto (janelas 1/3/5/10 min), faltas e cartões. Cada partida do
   RoboBet é **casada por nome das equipes** (tokens normalizados +
   confirmação do placar) com uma do SokkerPRO; se não casar ou se a chamada
   falhar, os campos ficam **N/D** — nada quebra.
3. **Cálculo do score**: três componentes (gols, escanteios, momentum) a partir
   somente de dados reais; o eixo dominante carrega o LPS. Sem estatísticas ao
   vivo confirmadas, o score recebe um **desconto de confiança (×0.82)** — um
   jogo com apenas probabilidades de modelo pode aparecer como "interessante",
   mas dificilmente como "muito forte".
4. **API JSON** `/api/scanner`: resumo, fontes, oportunidades ordenadas (maior
   LPS primeiro, máx. 10).
5. **Frontend** (página única, sem frameworks): atualiza a cada 30 s, reordena,
   remove jogos encerrados, adiciona novos, detecta **alertas** (🔥 nova
   oportunidade ≥ 80, gol, mudança de entrada).

## O LIVE PRESSURE SCORE (0–100)

| Faixa  | Classificação        |
|--------|----------------------|
| 80–100 | 🟢 Oportunidade muito forte |
| 70–79  | 🟡 Oportunidade interessante |
| 60–69  | 🟠 Observar           |
| < 60   | 🔴 Ignorar            |

O score combina dois eixos:

* **Potencial de gols** — probabilidade de gol no restante (over 1.5 do modelo),
  base de gol (over 0.5), over 2.5, BTTS (jogo aberto), ritmo de criação
  (gols + xG por minuto), gol recente, pressão constante; com SokkerPRO:
  finalizações, no alvo, xG, ataques perigosos, grandes chances.
* **Potencial de escanteios** — probabilidade do modelo de escanteio na janela
  de 10 min mais próxima, escanteios esperados no total, sugestão de mercado
  de escanteios, pressão constante; com SokkerPRO: escanteios reais por minuto,
  ataques perigosos, finalizações bloqueadas.
* **Momentum** — gol recente, bandeira 🔥 (pressão constante), cartões,
  placar aberto, segundo tempo, posse equilibrada, ataques perigosos, xG,
  **ataques perigosos nos últimos 10 min** e **barra de pressão** do SokkerPRO.

O **eixo dominante** (gols ou escanteios) carrega ~88% do score; o outro eixo
reforça proporcionalmente (~12%), e o momentum ajusta dentro de uma faixa.
Assim, um jogo quente em gols não é rebaixado por ter poucos escanteios.

### Classificação da oportunidade

* ⚽ **GOLS** quando o componente de gols ≥ 55 → sugere *Over 0.5 gol*,
  *Over 1.5 gols* ou *Próximo gol* conforme as probabilidades do modelo.
* 🚩 **ESCANTEIOS** quando o componente de escanteios ≥ 55 → *Over de
  escanteios* (usa a sugestão do modelo quando existir, ex.: "+7.5").
* ⚽🚩 **GOLS + ESCANTEIOS** quando ambos.
* ❌ **SEM ENTRADA** caso contrário — não se força entrada.

A **confiança** (Alta/Média/Baixa) vem das probabilidades que sustentam a
entrada e da corroboração das estatísticas ao vivo.

## Honestidade dos dados (regras seguidas)

* **Nunca inventamos estatística.** xG, finalizações, ataques perigosos,
  escanteios, placar e minuto vêm ou do RoboBet ou do SokkerPRO; ausente = **N/D**.
* As probabilidades de gol/escanteio são do **modelo RoboBet** e estão sempre
  rotuladas como tal ("modelo") na interface.
* O SokkerPRO tem endpoint público de livescores; usamos uma chamada por ciclo
  com intervalo mínimo de 60 s. O RoboBet guarda estatísticas premium em
  payloads criptografados para contas pagas — não tentamos contornar isso.
  Respeite os termos de uso das fontes e use com moderação.
* "Possível entrada" é indicação estatística, **não garantia de resultado**.

## Estrutura do projeto

```
server.py            # servidor HTTP (stdlib): poll, enriquecimento, API, estáticos
scanner/
  robobet.py         # cliente da API pública do RoboBet
  sokkerpro.py       # estatísticas ao vivo do SokkerPRO + casamento por nomes
  scorer.py          # LIVE PRESSURE SCORE + classificação de oportunidade
static/
  index.html         # página única
  style.css          # tema escuro responsivo
  app.js             # polling, render, alertas
```
