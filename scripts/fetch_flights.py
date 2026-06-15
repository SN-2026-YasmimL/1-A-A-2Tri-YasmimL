"""
fetch_flights.py — SIROS/ANAC + Supabase v2
Melhorias aplicadas:
  - Logs renomeados: "enviados/processados" em vez de "inseridos/atualizados"
  - Upsert explicado: evita duplicatas via constraint voos_unique
  - execucoes registra: voos_processados, lotes_enviados, erros
  - Falha parcial gera status "erro_parcial" e falha o workflow (exit 1)
  - Falha crítica gera status "erro_critico"

Variáveis de ambiente:
  SUPABASE_URL         → URL do projeto (GitHub Secret)
  SUPABASE_SERVICE_KEY → secret key / service_role key (GitHub Secret)
  AIRPORTS             → ICAOs separados por vírgula (GitHub Variable)
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests
from supabase import create_client

# ── Credenciais ───────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[ERRO CRÍTICO] SUPABASE_URL e SUPABASE_SERVICE_KEY são obrigatórios.")
    print("              Configure-os como GitHub Secrets no repositório.")
    sys.exit(1)

db = create_client(SUPABASE_URL, SUPABASE_KEY)
print(f"Supabase conectado: {SUPABASE_URL}")

# ── Configurações ─────────────────────────────────────────────────────────────

API_BASE     = "https://sas.anac.gov.br/sas/siros_api"
airports_env = os.environ.get("AIRPORTS", "SBCA")
AIRPORTS     = [a.strip().upper() for a in airports_env.split(",") if a.strip()]
LOTE         = 500   # registros por requisição ao Supabase

BRT      = timezone(timedelta(hours=-3))
hoje     = datetime.now(BRT)
data_ref = hoje.strftime("%d%m%Y")
data_iso = hoje.strftime("%Y-%m-%d")

print(f"Data de referência: {hoje.strftime('%d/%m/%Y')} (BRT)")
print(f"Aeroportos configurados: {', '.join(AIRPORTS)}")

# ── Mapeamentos ───────────────────────────────────────────────────────────────

AIRLINES = {
    "GLO": "GOL",     "TAM": "LATAM",   "AZU": "Azul",
    "ONE": "VOEPASS",  "PTB": "Passaredo","TAP": "TAP Portugal",
    "DAL": "Delta",   "UAL": "United",   "AFR": "Air France",
    "DLH": "Lufthansa","IBE": "Iberia",  "AAL": "American Airlines",
    "AVA": "Avianca", "BAW": "British Airways","UAE": "Emirates",
    "THY": "Turkish Airlines","SKU": "Sky Airline","CMP": "Copa Airlines",
}

EQUIPAMENTOS = {
    "A20N":"Airbus A320neo","A21N":"Airbus A321neo","A319":"Airbus A319",
    "A320":"Airbus A320","A321":"Airbus A321","A332":"Airbus A330-200",
    "A333":"Airbus A330-300","A339":"Airbus A330-900neo",
    "A359":"Airbus A350-900","B737":"Boeing 737","B738":"Boeing 737-800",
    "B38M":"Boeing 737 MAX 8","B748":"Boeing 747-8","B763":"Boeing 767-300",
    "B77W":"Boeing 777-300ER","B788":"Boeing 787-8","B789":"Boeing 787-9",
    "E190":"Embraer E190","E195":"Embraer E195","E295":"Embraer E195-E2",
    "AT76":"ATR 72",
}


def get_airline(icao: str) -> str:
    return AIRLINES.get((icao or "").strip().upper(), (icao or "").strip() or "?")


def get_equip(icao: str) -> str | None:
    code = (icao or "").strip().upper()
    return EQUIPAMENTOS.get(code, code or None)


def get_tipo_operacao(ds: str) -> str:
    return "Internacional" if "INTERNAC" in (ds or "").upper() else "Doméstico"


def parse_siros_dt(dt_str: str) -> str | None:
    """Converte 'DD/MM/YYYY HH:MM' (UTC da API) para ISO com timezone UTC."""
    if not dt_str or len(dt_str) < 16:
        return None
    try:
        dt = datetime.strptime(dt_str.strip(), "%d/%m/%Y %H:%M")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return None


def parse_hora(dt_str: str) -> str | None:
    """Extrai HH:MM:00 de 'DD/MM/YYYY HH:MM'."""
    if not dt_str or len(dt_str) < 16:
        return None
    try:
        return dt_str.strip()[11:16] + ":00"
    except Exception:
        return None


# ── Busca voos no SIROS ───────────────────────────────────────────────────────

def buscar_voos_siros() -> list:
    url = f"{API_BASE}/voos"
    print(f"\nGET {url}?dataReferencia={data_ref}")
    try:
        r = requests.get(url, params={"dataReferencia": data_ref}, timeout=60)
        r.raise_for_status()
        decoded = r.json()
        if isinstance(decoded, str):
            decoded = json.loads(decoded)
        if isinstance(decoded, list):
            print(f"  Total retornado pela API SIROS: {len(decoded)} voos")
            return decoded
        print(f"  [AVISO] Formato inesperado na resposta: {type(decoded)}")
        return []
    except Exception as e:
        print(f"  [ERRO] Falha ao buscar voos no SIROS: {e}")
        return []


def normalizar_voo(f: dict) -> dict:
    empresa = (f.get("sg_empresa_icao")          or "").strip()
    nr_voo  = (f.get("nr_voo")                   or "").strip().lstrip("0") or "0"
    etapa   = str(f.get("nr_etapa")              or "1").strip()
    equip   = (f.get("sg_equipamento_icao")       or "").strip()
    assent  = f.get("qt_assentos_previstos")
    partida = (f.get("dt_partida_prevista_utc")  or "").strip()
    chegada = (f.get("dt_chegada_prevista_utc")  or "").strip()
    tipo    = (f.get("ds_tipo_servico")           or "").strip()
    origem  = (f.get("sg_icao_origem")            or "").strip().upper()
    destino = (f.get("sg_icao_destino")           or "").strip().upper()

    return {
        "data_referencia": data_iso,
        "icao_empresa":    empresa or None,
        "nome_empresa":    get_airline(empresa),
        "numero_voo":      nr_voo,
        "etapa":           etapa,
        "icao_origem":     origem or None,
        "icao_destino":    destino or None,
        "hr_partida_utc":  parse_hora(partida),
        "hr_chegada_utc":  parse_hora(chegada),
        "partida_iso":     parse_siros_dt(partida),
        "chegada_iso":     parse_siros_dt(chegada),
        "equipamento":     get_equip(equip),
        "assentos":        int(assent) if assent and str(assent).isdigit() else None,
        "tipo_operacao":   get_tipo_operacao(tipo),
        "tipo_servico":    tipo or None,
    }


def registrar_execucao(
    aeroportos: list,
    voos_processados: int,
    lotes_enviados: int,
    erros: int,
    status: str,
    obs: str = "",
) -> None:
    """Grava o log de execução na tabela execucoes."""
    try:
        db.table("execucoes").insert({
            "concluido_em":        datetime.now(timezone.utc).isoformat(),
            "aeroportos_buscados": aeroportos,
            "voos_processados":    voos_processados,
            "lotes_enviados":      lotes_enviados,
            "erros":               erros,
            "status":              status,
            "observacao":          obs or None,
        }).execute()
        print(f"\n  Log de execução salvo — status: {status}")
    except Exception as e:
        print(f"  [AVISO] Não foi possível salvar o log de execução: {e}")


# ── Execução principal ────────────────────────────────────────────────────────

todos_voos = buscar_voos_siros()

if not todos_voos:
    print("\n[AVISO] Nenhum voo retornado pela API SIROS. Encerrando.")
    registrar_execucao(AIRPORTS, 0, 0, 0, "sem_dados",
                       "API SIROS não retornou voos para a data.")
    sys.exit(0)

# Filtra pelos aeroportos configurados e normaliza os registros
registros = []
for f in todos_voos:
    origem  = (f.get("sg_icao_origem")  or "").strip().upper()
    destino = (f.get("sg_icao_destino") or "").strip().upper()
    if origem not in AIRPORTS and destino not in AIRPORTS:
        continue
    empresa = (f.get("sg_empresa_icao") or "").strip()
    nr_voo  = (f.get("nr_voo")          or "").strip()
    if not empresa or not nr_voo or not origem or not destino:
        continue
    registros.append(normalizar_voo(f))

print(f"\nRegistros filtrados para os aeroportos configurados: {len(registros)}")
print(
    "  Obs: o upsert usa constraint voos_unique "
    "(data_referencia + icao_empresa + numero_voo + icao_origem + icao_destino + etapa). "
    "Voos já existentes são atualizados — sem duplicatas."
)

# Envio em lotes ao Supabase
total_processados = 0
total_lotes       = 0
total_erros       = 0

for i in range(0, len(registros), LOTE):
    lote     = registros[i:i + LOTE]
    num_lote = i // LOTE + 1
    try:
        db.table("voos").upsert(
            lote,
            on_conflict="data_referencia,icao_empresa,numero_voo,icao_origem,icao_destino,etapa",
        ).execute()
        total_processados += len(lote)
        total_lotes       += 1
        print(f"  Lote {num_lote}: {len(lote)} registros enviados/processados")
    except Exception as e:
        total_erros += 1
        print(f"  [ERRO] Lote {num_lote} falhou: {e}")

# Define status final
if total_erros == 0:
    status_final = "concluido"
elif total_processados > 0:
    status_final = "erro_parcial"
else:
    status_final = "erro_critico"

obs = (
    f"Data: {data_iso} | Aeroportos: {', '.join(AIRPORTS)} | "
    f"Processados: {total_processados} | Lotes: {total_lotes} | Erros: {total_erros}"
)

registrar_execucao(
    AIRPORTS, total_processados, total_lotes, total_erros, status_final, obs
)

print(f"\nConcluído — {total_processados} registros enviados/processados em {total_lotes} lote(s).")

# Falha o workflow se houver qualquer erro parcial
# (permite que o GitHub Actions marque o run como falha para monitoramento)
if total_erros > 0:
    print(f"\n[ATENÇÃO] {total_erros} lote(s) com erro — workflow finalizado com falha.")
    sys.exit(1)
