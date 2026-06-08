# 06-05-2026 — SIROS/ANAC

Sub-projeto do programa **SN-2026**.  
Painel de voos programados usando a **API oficial SIROS da ANAC** — sem autenticação, sem custo, sem limites.

Organização: [github.com/SN-2026](https://github.com/SN-2026)  
Site: [SN-2026.github.io/06-05-2026-siros](https://SN-2026.github.io/06-05-2026-siros/)

---

## O que é o SIROS

O SIROS (Sistema de Registros dos Serviços Aéreos) é o sistema da ANAC onde as companhias aéreas registram obrigatoriamente todos os seus voos programados, conforme a Resolução ANAC nº 440/2017.

A API pública disponibiliza:

| Endpoint | O que retorna |
|---|---|
| `/api/voos?dataReferencia=DDMMAAAA` | Todos os voos do dia |
| `/api/voosPeriodo?dataReferenciaInicio=...&dataReferenciaFinal=...` | Voos em um período |
| `/api/aerodromo?sg_aerodromo_icao_ou_iata=ICAO` | Dados de um aeroporto |
| `/api/registros` | Todos os registros vigentes |

## Vantagens em relação à AviationStack

| | AviationStack | **SIROS/ANAC** |
|---|---|---|
| Custo | 100 chamadas/mês | **Ilimitado** |
| Autenticação | API Key obrigatória | **Nenhuma** |
| Dados extras | Apenas status | **Aeronave, assentos, tipo** |
| Fonte | Privada | **Oficial do governo** |
| Cobertura | Mundial | Brasil (100% das rotas regulares) |

## Como configurar

### 1. Criar repositório na organização SN-2026
`github.com/SN-2026` → New repository → `06-05-2026-siros` → Public

### 2. Fazer upload dos arquivos
Arraste todos os arquivos deste ZIP para o repositório via interface web.

### 3. Ativar GitHub Pages
Settings → Pages → Branch: main / (root) → Save

### 4. Configurar a variável AIRPORTS
Settings → Variables → Actions → New repository variable  
Nome: `AIRPORTS`  
Valor: `SBCA,SBGR,SBSP,SBCT,SBGL,SBBR,SBFL,SBPA,SBSV,SBFZ`

> Sem limite de aeroportos — a API é gratuita e pública!

### 5. Executar o workflow
Actions → Atualizar dados de voos (SIROS/ANAC) → Run workflow

### 6. Acessar o site
```
https://SN-2026.github.io/06-05-2026-siros/
```

## Execução local

```bash
pip install requests
python scripts/fetch_flights.py

# Servir localmente
python -m http.server 8080
```

## Licença
MIT
