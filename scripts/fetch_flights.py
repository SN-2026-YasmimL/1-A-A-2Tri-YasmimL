"""
fetch_flights.py — SIROS/ANAC + Supabase v1.0
Busca voos do dia via API SIROS e insere/atualiza no Supabase.
Nao salva mais arquivos JSON no repositorio.

Variaveis de ambiente (GitHub Secrets):
  SUPABASE_URL         -> URL do projeto Supabase (ex: https://XXXX.supabase.co)
  SUPABASE_SERVICE_KEY -> service_role key (acesso total para escrita)

Variaveis de ambiente (GitHub Variables):
  AIRPORTS             -> ICAOs separados por virgula (ex: SBCA,SBGR,SBCT)
"""

import json
import os
from datetime import datetime, timezone, timedelta

import requests
from supabase import create_client

# ── Credenciais Supabase ──────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[ERRO] SUPABASE_URL e SUPABASE_SERVICE_KEY sao obrigatorios.")
    print("       Configure-os como GitHub Secrets no repositorio.")
    raise SystemExit(1)

db = create_client(SUPABASE_URL, SUPABASE_KEY)
print(f"Supabase conectado: {SUPABASE_URL}")

# ── Configuracoes ─────────────────────────────────────────────────────────────

API_BASE     = "https://sas.anac.gov.br/sas/siros_api"
airports_env = os.environ.get("AIRPORTS", "SBCA")
AIRPORTS     = [a.strip().upper() for a in airports_env.split(",") if a.strip()]

BRT      = timezone(timedelta(hours=-3))
hoje     = datetime.now(BRT)
data_ref = hoje.strftime("%d%m%Y")      # formato SIROS: DDMMYYYY
data_iso = hoje.strftime("%Y-%m-%d")    # formato banco: YYYY-MM-DD

print(f"Data de referencia: {hoje.strftime('%d/%m/%Y')} (BRT)")
print(f"Aeroportos: {', '.join(AIRPORTS)}")

# ── Mapeamentos ───────────────────────────────────────────────────────────────

AIRLINES = {
    "GLO":"GOL","TAM":"LATAM","AZU":"Azul","ONE":"VOEPASS",
    "PTB":"Passaredo","TAP":"TAP Portugal","DAL":"Delta",
    "UAL":"United","AFR":"Air France","DLH":"Lufthansa",
    "IBE":"Iberia","AAL":"American Airlines","AVA":"Avianca",
    "BAW":"British Airways","UAE":"Emirates","THY":"Turkish Airlines",
    "SKU":"Sky Airline","CMP":"Copa Airlines","LAN":"LATAM Internacional",
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
    return AIRLINES.get((icao or "").strip().upper(), (icao or "?").strip())

def get_equip(icao: str) -> str:
    return EQUIPAMENTOS.get((icao or "").strip().upper(), (icao or "").strip() or None)

def get_tipo_operacao(ds_tipo_servico: str) -> str:
    s = (ds_tipo_servico or "").upper()
    return "Internacional" if "INTERNAC" in s else "Domestico"

def parse_siros_dt(dt_str: str) -> str | None:
    """Converte 'DD/MM/YYYY HH:MM' (UTC) para ISO com timezone UTC."""
    if not dt_str or len(dt_str) < 16:
        return None
    try:
        dt = datetime.strptime(dt_str.strip(), "%d/%m/%Y %H:%M")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return None

def parse_hora(dt_str: str) -> str | None:
    """Extrai apenas HH:MM:00 de 'DD/MM/YYYY HH:MM'."""
    if not dt_str or len(dt_str) < 16:
        return None
    try:
        return dt_str.strip()[11:16] + ":00"
    except Exception:
        return None


# ── Busca todos os voos do dia no SIROS ───────────────────────────────────────

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
            print(f"  Total retornado pela API: {len(decoded)} voos")
            return decoded
        return []
    except Exception as e:
        print(f"  [ERRO] Falha ao buscar voos: {e}")
        return []


# ── Normaliza um voo para o schema do banco ────────────────────────────────────

def normalizar_voo(f: dict) -> dict:
    empresa  = (f.get("sg_empresa_icao")          or "").strip()
    nr_voo   = (f.get("nr_voo")                   or "").strip().lstrip("0") or "0"
    etapa    = str(f.get("nr_etapa")              or "1").strip()
    equip    = (f.get("sg_equipamento_icao")       or "").strip()
    assentos = f.get("qt_assentos_previstos")
    partida  = (f.get("dt_partida_prevista_utc")  or "").strip()
    chegada  = (f.get("dt_chegada_prevista_utc")  or "").strip()
    tipo_srv = (f.get("ds_tipo_servico")           or "").strip()
    origem   = (f.get("sg_icao_origem")            or "").strip().upper()
    destino  = (f.get("sg_icao_destino")           or "").strip().upper()

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
        "equipamento":     get_equip(equip) or None,
        "assentos":        int(assentos) if assentos and str(assentos).isdigit() else None,
        "tipo_operacao":   get_tipo_operacao(tipo_srv),
        "tipo_servico":    tipo_srv or None,
    }


# ── Registra execucao no banco ────────────────────────────────────────────────

def registrar_execucao(aeroportos: list, inseridos: int, atualizados: int, status: str, obs: str = "") -> None:
    try:
        db.table("execucoes").insert({
            "concluido_em":       datetime.now(timezone.utc).isoformat(),
            "aeroportos_buscados": aeroportos,
            "voos_inseridos":     inseridos,
            "voos_atualizados":   atualizados,
            "status":             status,
            "observacao":         obs or None,
        }).execute()
    except Exception as e:
        print(f"  [AVISO] Nao foi possivel registrar execucao: {e}")


# ── Execucao principal ────────────────────────────────────────────────────────

todos_voos = buscar_voos_siros()
total_inseridos  = 0
total_atualizados = 0

if not todos_voos:
    print("\n[AVISO] Nenhum voo retornado. Encerrando.")
    registrar_execucao(AIRPORTS, 0, 0, "sem_dados", "API SIROS nao retornou voos.")
    raise SystemExit(0)

# Filtra apenas voos dos aeroportos configurados e normaliza
registros = []
for f in todos_voos:
    origem  = (f.get("sg_icao_origem")  or "").strip().upper()
    destino = (f.get("sg_icao_destino") or "").strip().upper()

    if origem not in AIRPORTS and destino not in AIRPORTS:
        continue

    # Valida campos obrigatorios
    empresa = (f.get("sg_empresa_icao") or "").strip()
    nr_voo  = (f.get("nr_voo")          or "").strip()
    if not empresa or not nr_voo or not origem or not destino:
        continue

    registros.append(normalizar_voo(f))

print(f"\nVoos filtrados para os aeroportos configurados: {len(registros)}")

if registros:
    # Upsert em lotes de 500 para evitar timeout
    LOTE = 500
    for i in range(0, len(registros), LOTE):
        lote = registros[i:i+LOTE]
        try:
            resultado = db.table("voos").upsert(
                lote,
                on_conflict="data_referencia,icao_empresa,numero_voo,icao_origem,icao_destino,etapa"
            ).execute()
            total_inseridos += len(lote)
            print(f"  Lote {i//LOTE + 1}: {len(lote)} registros enviados ao Supabase")
        except Exception as e:
            print(f"  [ERRO] Falha no lote {i//LOTE + 1}: {e}")

registrar_execucao(
    AIRPORTS,
    total_inseridos,
    total_atualizados,
    "concluido",
    f"Data: {data_iso} | Aeroportos: {', '.join(AIRPORTS)}"
)

print(f"\nConcluido — {total_inseridos} registros enviados ao Supabase.")
print(f"Painel: {SUPABASE_URL.replace('https://', 'https://app.supabase.com/project/')}")
