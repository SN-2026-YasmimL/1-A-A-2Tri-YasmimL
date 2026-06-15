name: Pipeline SIROS → Supabase

on:
  schedule:
    # 4× por dia: 06h, 09h, 12h e 18h (Brasília = UTC-3)
    - cron: '0 9,12,15,21 * * *'
  workflow_dispatch:

# Permissões mínimas necessárias:
# - contents: read  → checkout do repositório
# Sem permissão de escrita no repo — dados vão direto ao Supabase
permissions:
  contents: read

# Evita execuções simultâneas do mesmo workflow no mesmo branch.
# cancel-in-progress: false garante que um run em andamento não seja
# cancelado se um novo for disparado (ex: disparo manual durante o cron)
concurrency:
  group: siros-supabase-${{ github.ref }}
  cancel-in-progress: false

jobs:
  fetch-and-insert:
    runs-on: ubuntu-latest
    # Timeout de segurança: encerra o job após 10 minutos
    # evita jobs presos consumindo minutos do plano gratuito
    timeout-minutes: 10

    steps:
      - name: Checkout do repositório
        uses: actions/checkout@v4

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Instalar dependências
        run: pip install requests supabase

      - name: Buscar SIROS e inserir no Supabase
        run: python scripts/fetch_flights.py
        env:
          AIRPORTS:             ${{ vars.AIRPORTS || 'SBCA,SBGR,SBSP,SBCT,SBGL,SBBR,SBFL,SBPA,SBSV,SBFZ' }}
          SUPABASE_URL:         ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}

      # Sem etapa de commit — dados vão direto ao Supabase
      # O repositório armazena apenas código
