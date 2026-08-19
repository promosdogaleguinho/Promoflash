# promoflash-bot

Bot worker em Python para buscar promoções em APIs de lojas e marketplaces com programa de afiliados e enviar para canais/grupos.

- **Nome técnico do projeto:** `promoflash-bot`
- **Nome do bot:** PromoFlash Bot
- **Marca pública/comunidade:** Promos do Galeguinho
- **Personagem/comunicador:** Galeguinho

## O que é

O PromoFlash Bot é um worker que coleta promoções, normaliza os dados, agrupa ofertas parecidas, escolhe a melhor oferta, evita reenvios repetidos e publica nos canais configurados — começando pelo Telegram.

O MVP usa um `MockCollector` para simular promoções e permite evoluir depois com integrações reais (Shopee, etc.).

## Arquitetura resumida

```text
Collector → Normalizer → Category Resolver → Product Identity
→ Offer Grouper → Offer Ranker → Repost Policy → Router
→ Formatter → Channel Sender → Persistence
```

Veja detalhes em [ARCHITECTURE.md](ARCHITECTURE.md).

## Como rodar localmente

```bash
pip install -r requirements.txt
python -m app.main
```

## Dry-run (padrão)

Por padrão, `TELEGRAM_DRY_RUN=true` (definido no `.env.example`). Nesse modo:

- o bot **não envia** mensagens reais;
- apenas registra `chat_id` e mensagem no log;
- **não exige** `TELEGRAM_BOT_TOKEN`.

```bat
set TELEGRAM_DRY_RUN=true
python -m app.main
```

## Configurando Telegram real

### Variáveis de ambiente

| Variável | Valor | Comportamento |
|---|---|---|
| `TELEGRAM_DRY_RUN` | `true` | Não envia mensagem real |
| `TELEGRAM_DRY_RUN` | `false` | Envia mensagem real |
| `TELEGRAM_BOT_TOKEN` | token do BotFather | Obrigatório quando `TELEGRAM_DRY_RUN=false` |
| `TELEGRAM_SEND_INTERVAL_SECONDS` | `1.5` | Intervalo mínimo entre envios (evita erro 429 do Telegram) |
| `MAX_PRODUCTS_PER_RUN` | `10` | Máximo de produtos enviados por execução (os melhores por score; o restante fica para a próxima) |

### Limites do Telegram (erro 429)

O Telegram limita a frequência de mensagens (aproximadamente 1 por segundo por chat e ~20 por minuto em grupos). Para respeitar isso:

- O `TelegramSender` aguarda `TELEGRAM_SEND_INTERVAL_SECONDS` entre envios.
- Ao receber `429 Too Many Requests`, ele respeita o `retry_after` informado e tenta novamente (com teto de segurança).
- `MAX_PRODUCTS_PER_RUN` limita quantos produtos saem por execução; os demais são adiados para a próxima rodada (não são perdidos, pois não entram no histórico de enviados).

**Importante:** nunca commite o `TELEGRAM_BOT_TOKEN`. Use variáveis de ambiente ou secrets do deploy.

### Passo a passo

1. Crie um bot com o [@BotFather](https://t.me/BotFather) e copie o token.
2. Crie um grupo ou canal de teste (ex.: "Promos do Galeguinho - Teste").
3. Adicione o bot no grupo ou canal.
4. Se for **canal**, adicione o bot como **administrador**.
5. Envie uma mensagem no grupo/canal (isso gera um update na API).
6. Descubra o `chat_id` com o script auxiliar.
7. Atualize os `chat_id` em `config/channels.json`.
8. Rode o bot com `TELEGRAM_DRY_RUN=false`.

Os valores atuais em `config/channels.json` (`DRY_RUN_GERAL`, `DRY_RUN_GAMES`, etc.) são placeholders para desenvolvimento. Substitua pelos IDs reais antes de enviar mensagens de verdade.

Exemplo de destino real:

```json
"games": {
  "chat_id": "-1001234567890",
  "enabled": true
}
```

### Descobrir `chat_id`

**PowerShell:**

```powershell
$env:TELEGRAM_BOT_TOKEN="seu_token_aqui"
python scripts/get_telegram_chat_id.py
```

**CMD:**

```bat
set TELEGRAM_BOT_TOKEN=seu_token_aqui
python scripts/get_telegram_chat_id.py
```

Saída esperada:

```text
Found chats:

Title: Promos do Galeguinho - Teste
Type: supergroup
Chat ID: -1001234567890
```

Se não aparecer nada:

```text
Nenhum update encontrado. Envie uma mensagem no grupo/canal com o bot adicionado e rode novamente.
```

### Enviar mensagens reais

**CMD:**

```bat
set TELEGRAM_BOT_TOKEN=seu_token_aqui
set TELEGRAM_DRY_RUN=false
python -m app.main
```

**PowerShell:**

```powershell
$env:TELEGRAM_BOT_TOKEN="seu_token_aqui"
$env:TELEGRAM_DRY_RUN="false"
python -m app.main
```

Com o ambiente virtual do projeto:

```powershell
.\.venv\Scripts\python.exe -m app.main
```

## Executar testes

```bash
pytest
```

## Modos de execução

| Variável | Valor | Comportamento |
|---|---|---|
| `RUN_MODE` | `once` | Executa uma vez e encerra |
| `RUN_MODE` | `worker` | Executa em loop a cada `SLEEP_INTERVAL_SECONDS` (padrão: 600s = 10 min) |

## Persistência em produção

O controle de envios fica em `data/sent_promotions.json`.

O `JsonPersistence` cria automaticamente o arquivo com `{"sent_promotions": []}` quando ele não existe.

Em produção com **GitHub Actions**, esse arquivo é versionado no repositório e atualizado a cada execução (evita reenvios duplicados entre runs).

## Deploy com GitHub Actions (recomendado)

O bot roda **de graça** em repositório privado via cron, sem servidor 24/7.

- Workflow: `.github/workflows/promoflash.yml`
- Frequência padrão: **3 vezes ao dia** — 08:00, 13:00 e 19:00 (horário de Brasília)
- Modo: `RUN_MODE=once` (uma execução por trigger)
- Histórico: commit automático de `data/sent_promotions.json` com `[skip ci]`

### Passo a passo

1. Crie um repositório **privado** no GitHub e envie o código.
2. Em **Settings → Secrets and variables → Actions**, cadastre:

| Secret | Obrigatório |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Sim |
| `ALIEXPRESS_APP_KEY` | Sim |
| `ALIEXPRESS_APP_SECRET` | Sim |
| `ALIEXPRESS_TRACKING_ID` | Não |

3. Confirme que `config/channels.json` tem os `chat_id` reais do Telegram.
4. Confirme que `config/sources.json` tem `aliexpress.enabled=true` e `mock.enabled=false`.
5. Na aba **Actions → PromoFlash Worker → Run workflow**, dispare um teste manual.
6. O cron passa a rodar automaticamente **3 vezes ao dia** (08:00, 13:00 e 19:00 BRT).

### Ajustar horários

Edite o cron em `.github/workflows/promoflash.yml` (GitHub usa **UTC**; Brasília = UTC−3):

```yaml
# 08:00, 13:00 e 19:00 BRT → 11:00, 16:00 e 22:00 UTC
- cron: "0 11,16,22 * * *"
```

Disparo manual continua disponível em **Actions → PromoFlash Worker → Run workflow**.

## Operação

### GitHub Actions (produção atual)

- O workflow roda **3 vezes ao dia** (08:00, 13:00 e 19:00 BRT) via cron.
- O histórico fica em `data/sent_promotions_*.json` no repositório (por fonte).
- O `concurrency` impede duas execuções ao mesmo tempo.
- Antes de rodar o bot, o job **sincroniza `origin/main`** (histórico de envios sempre atualizado).
- Commits automáticos do histórico usam `[skip ci]` para não disparar pipeline extra.
- O push do histórico tenta até 3 vezes; se falhar, o job falha (para não “esquecer” envios).
- Os arquivos `sent_*.json` **nunca são apagados automaticamente** pelo bot.

### Oracle Cloud (alternativa 24/7)

- VM Always Free com `RUN_MODE=worker` rodando em loop contínuo.
- Requer configuração de servidor (SSH, Python, systemd).

## Segurança

- Tokens e secrets devem ficar apenas em variáveis de ambiente ou **GitHub Secrets**.
- Nunca commite o token do Telegram.
- Nunca commite o App Secret da AliExpress.
- Nunca commite o arquivo `.env`.
- Se um token for exposto, **regenere imediatamente** no BotFather (Telegram) ou no OpenService (AliExpress).
- Os loggers `httpx` e `httpcore` permanecem em `WARNING` para evitar vazamento do token do Telegram na URL de request.

## Configurando AliExpress Affiliates API

Integração inicial usando a permissão **Standard API for Publishers** (não requer Advanced API).

### Passo a passo

1. Crie um app no [OpenService](https://openservice.aliexpress.com/) como `Dropshipping/Affiliates Developer`.
2. Use o perfil `Affiliates Individual/Corporation`.
3. Confirme que **Standard API for Publishers** está `Active`.
4. Copie o `AppKey` e o `App Secret`.
5. Configure as variáveis de ambiente (veja abaixo).
6. Rode o script de teste isolado para validar a conexão.
7. Ative `aliexpress.enabled=true` em `config/sources.json`.
8. Rode o worker primeiro com Telegram em **dry-run**.

**Importante:** nunca commite `ALIEXPRESS_APP_SECRET`. Ele é lido apenas de variáveis de ambiente e nunca é registrado em logs.

`ALIEXPRESS_APP_KEY` e `ALIEXPRESS_APP_SECRET` são obrigatórios somente quando `aliexpress.enabled=true`. `ALIEXPRESS_TRACKING_ID` é opcional no início.

### Testar conexão (PowerShell)

```powershell
$env:ALIEXPRESS_APP_KEY="seu_app_key"
$env:ALIEXPRESS_APP_SECRET="seu_app_secret"
$env:ALIEXPRESS_API_ENDPOINT="https://api-sg.aliexpress.com/sync"
$env:ALIEXPRESS_SIGN_METHOD="hmac"
$env:ALIEXPRESS_TARGET_CURRENCY="BRL"
$env:ALIEXPRESS_TARGET_LANGUAGE="PT"
$env:ALIEXPRESS_SHIP_TO_COUNTRY="BR"

python scripts/test_aliexpress_connection.py
```

### Rodar o worker em dry-run

Depois de validar a conexão e ativar `aliexpress.enabled=true`:

```powershell
$env:TELEGRAM_DRY_RUN="true"
python -m app.main
```

## Usando AliExpress como fonte real

Para o público brasileiro, use sempre **português**, **real (BRL)** e **Brasil**. O link enviado ao usuário vem do `promotion_link` (link de afiliado).

Internamente o parâmetro enviado à API é `country=BR` (não `ship_to_country`).

### Passo a passo

1. Configure `ALIEXPRESS_APP_KEY`.
2. Configure `ALIEXPRESS_APP_SECRET`.
3. Mantenha `ALIEXPRESS_TARGET_LANGUAGE=PT`.
4. Mantenha `ALIEXPRESS_TARGET_CURRENCY=BRL`.
5. Mantenha `ALIEXPRESS_SHIP_TO_COUNTRY=BR`.
6. Rode o script de diagnóstico.
7. Ative `aliexpress.enabled=true` em `config/sources.json`.
8. Opcionalmente desligue o mock com `mock.enabled=false`.
9. Rode primeiro com `TELEGRAM_DRY_RUN=true`.
10. Depois rode com `TELEGRAM_DRY_RUN=false` para enviar de verdade.

Mock e AliExpress podem rodar juntos (ambos `enabled=true`) ou você pode usar apenas AliExpress (mock `enabled=false`).

### Configuração e diagnóstico (PowerShell)

```powershell
$env:ALIEXPRESS_APP_KEY="seu_app_key"
$env:ALIEXPRESS_APP_SECRET="seu_app_secret"
$env:ALIEXPRESS_API_ENDPOINT="https://api-sg.aliexpress.com/sync"
$env:ALIEXPRESS_SIGN_METHOD="hmac"
$env:ALIEXPRESS_TARGET_CURRENCY="BRL"
$env:ALIEXPRESS_TARGET_LANGUAGE="PT"
$env:ALIEXPRESS_SHIP_TO_COUNTRY="BR"

python scripts/test_aliexpress_connection.py
```

### Rodar em dry-run

```powershell
$env:TELEGRAM_DRY_RUN="true"
python -m app.main
```

### Rodar envio real

```powershell
$env:TELEGRAM_DRY_RUN="false"
python -m app.main
```

### Sobre os preços da AliExpress

Os preços exibidos nas mensagens vêm da **AliExpress Affiliates API** (`aliexpress.affiliate.product.query`), usando os campos `target_app_sale_price` / `target_sale_price`. São os mesmos valores embutidos no link de afiliado.

Esses valores **podem diferir levemente do preço mostrado na página** por dois motivos:

- **Conversão de câmbio ao vivo:** a página converte para BRL no momento do acesso; a API traz um snapshot de câmbio. A diferença costuma ser proporcional e pequena (menos de 1%).
- **Produtos Choice e campanhas:** itens "Choice" e promoções (Choice Day, cupom de boas-vindas, desconto exclusivo do app) aplicam descontos extras que **não** aparecem na Affiliates API padrão. Nesses casos o site tende a mostrar um preço **menor** que o da mensagem — ou seja, o cliente nunca paga mais do que o anunciado.

Por isso, toda mensagem de AliExpress inclui um aviso curto:

```text
Obs.: preço sujeito a alteração no AliExpress.
```

Para inspecionar os campos de preço de um produto específico, use o script de debug:

```powershell
python scripts/debug_aliexpress_product_prices.py "fone bluetooth"
```

Não fazemos scraping da página nem usamos Selenium. Obter o preço final exato de produtos Choice exigiria a API de Hot Products/Choice, ainda não implementada.

## Regras de curadoria

O arquivo `config/promotion_rules.json` controla uma camada de curadoria automática aplicada **após** o filtro de qualidade e **antes** do envio.

Princípios:

- **Desconto não é obrigatório globalmente.** Ele é um **sinal positivo** que aumenta o score, não uma regra de bloqueio.
- **Produtos de alta intenção** (`high_intent_keywords`, ex.: `ps5`, `iphone`, `ssd`) podem passar mesmo com desconto baixo.
- **Palavras bloqueadas** (`blocked_keywords`, ex.: `réplica`, `fake`) **sempre rejeitam** a promoção.
- **Palavras estratégicas** (`preferred_keywords`) apenas **aumentam o score**, sem aprovar sozinhas.
- As regras podem ser ajustadas por **fonte** (`sources.aliexpress`) e por **categoria** (`categories.games`), que sobrescrevem a regra global.
- Após alterar o arquivo, basta rodar o bot novamente — não precisa mexer no código.

A busca por palavras ignora **acentos** e **maiúsculas/minúsculas** e funciona com termos compostos (ex.: `controle ps5`).

### Como a aprovação funciona

Primeiro passam as regras obrigatórias (título, preço dentro da faixa, sem palavra bloqueada, título não muito longo). Depois, a promoção é aprovada se cumprir **pelo menos uma** condição:

1. `promotion_score` ≥ `min_promotion_score`;
2. título com palavra de alta intenção **e** algum desconto (mesmo baixo);
3. campanha oficial (`is_official_campaign`);
4. `campaign_name` preenchido;
5. `sales` ≥ 100 **e** algum desconto.

### Exemplo

```text
Um PS5 com desconto pequeno pode passar porque é um produto de alta intenção.
Um produto genérico com desconto pequeno pode ser rejeitado por score baixo.
```

## AliExpress Advanced API

Com a permissão **Advanced API** aprovada, o bot passa a coletar promoções em três modos complementares, na seguinte prioridade conceitual:

```text
Featured Promotions → Hot Products → Product Search (palavra-chave)
```

- **Hot Products** (`aliexpress.affiliate.hotproduct.query`) busca produtos em alta.
- **Featured Promotions** (`aliexpress.affiliate.featuredpromo.get` + `aliexpress.affiliate.featuredpromo.products.get`) busca campanhas e coleções oficiais.
- **Product Search** (`aliexpress.affiliate.product.query`) continua como complemento e fallback.
- Campanhas oficiais recebem a tag `Campanha oficial` e o nome amigável da campanha.
- Produtos que aparecem em mais de um modo são **consolidados** pelo Promotion Merger (nunca enviados duplicados).
- Falha em qualquer modo da Advanced API **não impede** os demais collectors (a Standard API continua funcionando).
- **Smart Match** (`aliexpress.affiliate.product.smartmatch`) está preparado no client, mas **não participa** do fluxo principal nesta etapa (recurso experimental para recomendação futura por contexto/produto/categoria).
- Idioma, moeda e país permanecem `PT`, `BRL` e `BR`.

### Nomes amigáveis de campanhas

| Coleção (técnica) | Exibição |
|---|---|
| Hot Product | Produto em alta |
| New Arrival | Novidade |
| Best Seller | Mais vendido |
| Weekly Deals | Oferta da semana |

### Configuração em `config/sources.json`

```text
aliexpress_hot_products.enabled           liga/desliga o collector de produtos em alta
aliexpress_featured_promotions.enabled    liga/desliga o collector de campanhas oficiais
max_campaigns_per_run                     máximo de campanhas consultadas por execução
max_items_per_campaign                    máximo de produtos por campanha
max_items_per_run                         máximo de produtos por execução (por collector)
allowed_campaigns                         lista de campanhas permitidas (vazio = todas)
blocked_campaigns                         lista de campanhas bloqueadas
```

### Validar a Advanced API

```bash
python scripts/test_aliexpress_hot_products.py
python scripts/test_aliexpress_featured_promotions.py
pytest
python -m app.main
```

Rode primeiro com `TELEGRAM_DRY_RUN=true` para validar sem enviar mensagens reais.

## Cupons e campanhas promocionais

O bot suporta dois tipos de publicação promocional, além das promoções de produto normais:

- **Cupom vinculado a um produto:** aparece na própria mensagem do produto, com botão separado para resgatar o cupom quando o link for diferente.
- **Campanha independente de cupom:** publicação sem produto específico (ex.: cupom geral do Mercado Livre, evento AliExpress com vários cupons).

Princípios importantes:

- **AliExpress** pode fornecer cupons automaticamente **apenas** quando a resposta oficial da API traz esses dados (sem scraping, sem HTML).
- **Shopee** e **Mercado Livre** usam **configuração manual** (`config/coupons.json`) nesta etapa.
- Cupons **nunca são inferidos** sem vínculo explícito com o produto/campanha.
- Preços com cupom **não são calculados automaticamente**: o preço do produto continua sendo o valor retornado pela fonte e o benefício do cupom é exibido separadamente.
- **Cupons expirados não são enviados.**
- **Campanhas futuras** podem ter anúncio antecipado (`announce_before_start` + `announcement_at`).
- Mensagens suportam **múltiplos botões** (`MessageAction`); o Telegram os converte em teclado inline. A arquitetura já está preparada para o WhatsApp (via `append_actions_as_text` quando o canal não suportar botões).
- Os campos legados `coupon_code`/`coupon_description` da `Promotion` continuam existindo por **compatibilidade temporária** e são convertidos automaticamente para um `Coupon`.

O histórico de campanhas de cupom é persistido separadamente em `data/sent_coupon_campaigns.json`, sem afetar `data/sent_promotions.json`. A janela antispam de recampanha é controlada por `COUPON_REPOST_WINDOW_HOURS` (padrão `12`).

### Configuração manual

O arquivo `config/coupons.json` permite cadastrar campanhas e vínculos de cupom por produto para qualquer loja. Estrutura:

- `timezone`: fuso usado para validade e agendamento (padrão `America/Sao_Paulo`).
- `campaigns`: lista de campanhas independentes (cada uma com um ou mais cupons).
- `product_bindings`: vínculos manuais de cupom a um produto específico (`source` + `external_product_id`).

Todos os exemplos vêm com `"enabled": false` e **não devem ser ativados** com códigos reais sem validar a validade. Para ativar, defina `"enabled": true` na campanha ou binding desejado.

Valide as mensagens de cupom com dados fictícios (sem chamar APIs nem enviar Telegram):

```bash
pytest
python scripts/preview_coupon_messages.py
python -m app.main
```

Para inspecionar cupons reais retornados pela AliExpress (chamada real, uso manual, saída sanitizada):

```bash
python scripts/debug_aliexpress_coupons.py
```

## Shopee (stub)

`ShopeeCollector` e `ShopeeAffiliateClient` existem apenas como stubs com TODOs para implementação futura. Não fazem chamadas reais à API.

## Próximos passos

- Gerar links de afiliado reais via `aliexpress.affiliate.link.generate`
- Promover o Smart Match a collector real (recomendação por contexto/produto/categoria)
- Implementar integração real com Shopee Affiliate API
- Implementar WhatsApp sender (adapter próprio para `MessageAction`)
- Adicionar mais collectors (Amazon, Mercado Livre, etc.)
- Extração automática de cupons de Shopee e Mercado Livre (hoje manual)
- API de Choice para preço final exato (quando aprovado)
