"""
fetch_flights.py
Busca voos programados do dia na API SIROS/ANAC (gratuita, sem autenticacao).
Filtra por aeroporto(s) configurado(s) e salva em data/{ICAO}.json.

Variaveis de ambiente:
  AIRPORTS  -> ICAOs separados por virgula (ex: SBCA,SBGR)
               Padrao: SBCA

Documentacao da API:
  https://sas.anac.gov.br/sas/siros_api/

Endpoints utilizados:
  /api/voos?dataReferencia=DDMMAAAA   -> voos do dia
  /api/aerodromo?sg_aerodromo_icao_ou_iata=ICAO -> dados do aeroporto
"""

import json
import os
from datetime import datetime, timezone, timedelta

import requests

# ── Configuracoes ─────────────────────────────────────────────────────────────

API_BASE     = "https://sas.anac.gov.br/sas/siros_api/api"
airports_env = os.environ.get("AIRPORTS", "SBCA")
AIRPORTS     = [a.strip().upper() for a in airports_env.split(",") if a.strip()]

# Horario de Brasilia: UTC-3
BRT = timezone(timedelta(hours=-3))

# Data de hoje em Brasilia no formato ddMMaaaa exigido pela API
hoje     = datetime.now(BRT)
data_ref = hoje.strftime("%d%m%Y")        # ex: 10052026
data_iso = hoje.strftime("%Y-%m-%d")      # ex: 2026-05-10

print(f"SIROS/ANAC — Buscando voos para: {hoje.strftime('%d/%m/%Y')} (Brasilia)")
print(f"Aeroportos configurados: {', '.join(AIRPORTS)}")

# Mapa de companias aereas (ICAO -> nome)
AIRLINES = {
    "GLO": "GOL",
    "TAM": "LATAM",
    "AZU": "Azul",
    "ONE": "VOEPASS",
    "PTB": "Passaredo",
    "COA": "Copa Airlines",
    "AAL": "American Airlines",
    "UAL": "United Airlines",
    "DAL": "Delta Air Lines",
    "AFR": "Air France",
    "DLH": "Lufthansa",
    "IBE": "Iberia",
    "KLM": "KLM",
    "LAN": "LATAM",
    "AEA": "Air Europa",
}

# Mapa de equipamentos (ICAO -> nome legivel)
EQUIPAMENTOS = {
    "A20N": "Airbus A320neo",
    "A21N": "Airbus A321neo",
    "A319": "Airbus A319",
    "A320": "Airbus A320",
    "A321": "Airbus A321",
    "A332": "Airbus A330-200",
    "A333": "Airbus A330-300",
    "A343": "Airbus A340-300",
    "A359": "Airbus A350-900",
    "B737": "Boeing 737",
    "B738": "Boeing 737-800",
    "B739": "Boeing 737-900",
    "B38M": "Boeing 737 MAX 8",
    "B763": "Boeing 767-300",
    "B772": "Boeing 777-200",
    "B77W": "Boeing 777-300ER",
    "B788": "Boeing 787-8",
    "B789": "Boeing 787-9",
    "E190": "Embraer E190",
    "E195": "Embraer E195",
    "E295": "Embraer E195-E2",
    "AT76": "ATR 72",
    "AT75": "ATR 72-500",
    "DH8D": "Dash 8-400",
    "C208": "Cessna Caravan",
}

# Mapa de tipos de operacao
TIPO_OPERACAO = {
    "D": "Domestico",
    "I": "Internacional",
}

TIPO_SERVICO = {
    "P": "Passageiros",
    "C": "Carga",
    "M": "Misto",
}


def get_airline_name(icao_empresa: str) -> str:
    if not icao_empresa:
        return "?"
    code = icao_empresa.strip().upper()
    return AIRLINES.get(code, code)


def get_equipment_name(icao_equip: str) -> str:
    if not icao_equip:
        return "?"
    code = icao_equip.strip().upper()
    return EQUIPAMENTOS.get(code, code)


def converter_utc_para_brt(horario_utc: str, data_base: str) -> str:
    """
    Converte horario no formato HH:MM (UTC) para BRT (UTC-3).
    data_base no formato YYYY-MM-DD.
    Retorna string no formato HH:MM.
    """
    if not horario_utc or len(horario_utc) < 5:
        return horario_utc or "?"
    try:
        hora, minuto = int(horario_utc[:2]), int(horario_utc[3:5])
        dt_utc = datetime.fromisoformat(f"{data_base}T{hora:02d}:{minuto:02d}:00+00:00")
        dt_brt = dt_utc.astimezone(BRT)
        return dt_brt.strftime("%H:%M")
    except Exception:
        return horario_utc


def parse_datetime_brt(dt_str: str) -> str:
    """
    Converte datetime string da API (varios formatos possiveis) para ISO com BRT.
    """
    if not dt_str:
        return ""
    try:
        # Tenta formato ISO com timezone
        if "T" in dt_str:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.astimezone(BRT).isoformat()
        # Tenta formato de data+hora separado por espaco
        if " " in dt_str:
            dt = datetime.fromisoformat(dt_str)
            dt_utc = dt.replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(BRT).isoformat()
        return dt_str
    except Exception:
        return dt_str


def buscar_voos_do_dia() -> list:
    """
    Busca todos os voos programados para hoje via endpoint /api/voos.
    Retorna lista de dicionarios com os dados de cada voo.
    """
    url = f"{API_BASE}/voos"
    params = {"dataReferencia": data_ref}

    try:
        print(f"\nRequisicao: GET {url}?dataReferencia={data_ref}")
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()

        # A API pode retornar JSON array ou string CSV
        content_type = r.headers.get("content-type", "")
        raw = r.text.strip()

        # Tenta interpretar como JSON
        if raw.startswith("[") or raw.startswith("{"):
            data = r.json()
            if isinstance(data, list):
                print(f"  Retorno: {len(data)} voos no total (JSON)")
                return data
            elif isinstance(data, dict):
                # Pode estar em uma chave como "data" ou "voos"
                for key in ("data", "voos", "result", "results"):
                    if key in data and isinstance(data[key], list):
                        print(f"  Retorno: {len(data[key])} voos no total (JSON key={key})")
                        return data[key]
            return []

        # Tenta interpretar como CSV com separador ";"
        if ";" in raw:
            linhas = [l for l in raw.splitlines() if l.strip()]
            if not linhas:
                return []

            # Primeira linha pode ser cabecalho
            cabecalho = [c.strip() for c in linhas[0].split(";")]

            # Verifica se e realmente um cabecalho (contem texto nao numerico)
            if any(not c[:1].isdigit() for c in cabecalho[:3]):
                dados = linhas[1:]
            else:
                # Sem cabecalho — usa nomes padrao da documentacao
                cabecalho = [
                    "dt_inicio", "cd_icao_empresa", "nr_etapa", "nr_voo",
                    "cd_icao_equipamento", "qt_assentos", "cd_icao_origem",
                    "dt_hr_partida_prevista", "cd_icao_destino",
                    "dt_hr_chegada_prevista", "tp_operacao", "codeshare"
                ]
                dados = linhas

            result = []
            for linha in dados:
                cols = [c.strip() for c in linha.split(";")]
                voo = {}
                for i, campo in enumerate(cabecalho):
                    voo[campo] = cols[i] if i < len(cols) else ""
                result.append(voo)

            print(f"  Retorno: {len(result)} voos no total (CSV)")
            return result

        print(f"  [AVISO] Formato de resposta nao reconhecido.")
        return []

    except requests.exceptions.HTTPError as e:
        print(f"  [ERRO] HTTP {r.status_code}: {e}")
        return []
    except Exception as e:
        print(f"  [ERRO] Falha ao buscar voos: {e}")
        return []


def buscar_dados_aerodromo(icao: str) -> dict:
    """
    Busca dados complementares de um aeroporto via /api/aerodromo.
    """
    url = f"{API_BASE}/aerodromo"
    try:
        r = requests.get(url, params={"sg_aerodromo_icao_ou_iata": icao}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        return {}
    except Exception as e:
        print(f"  [AVISO] Nao foi possivel buscar dados do aerodromo {icao}: {e}")
        return {}


def normalizar_campo(voo: dict, *chaves) -> str:
    """Tenta multiplas chaves possiveis e retorna o primeiro valor encontrado."""
    for chave in chaves:
        val = voo.get(chave, "")
        if val:
            return str(val).strip()
    return ""


def filtrar_e_normalizar(todos_voos: list, icao: str) -> tuple[list, list]:
    """
    Filtra os voos pelo aeroporto ICAO (como origem OU destino)
    e normaliza os campos para o formato de saida.
    """
    chegadas   = []
    partidas   = []

    # Possiveis nomes de campo para aeroporto de origem e destino
    campos_origem  = ("cd_icao_origem", "icaoOrigem", "sg_icao_origem",
                      "aeroporto_origem", "origem_icao", "dep_icao")
    campos_destino = ("cd_icao_destino", "icaoDestino", "sg_icao_destino",
                      "aeroporto_destino", "destino_icao", "arr_icao")
    campos_empresa = ("cd_icao_empresa", "icaoEmpresa", "empresa_icao", "cia_icao")
    campos_voo     = ("nr_voo", "numeroVoo", "numero_voo", "flight_number")
    campos_equip   = ("cd_icao_equipamento", "equipamento", "equip_icao", "equipment")
    campos_partida = ("dt_hr_partida_prevista", "horarioPartida", "hr_partida",
                      "partida_prevista", "departure_scheduled")
    campos_chegada = ("dt_hr_chegada_prevista", "horarioChegada", "hr_chegada",
                      "chegada_prevista", "arrival_scheduled")
    campos_assento = ("qt_assentos", "quantidadeAssentos", "assentos", "seats")
    campos_op      = ("tp_operacao", "tipoOperacao", "tipo_operacao", "operation_type")
    campos_etapa   = ("nr_etapa", "numeroEtapa", "etapa")

    for voo in todos_voos:
        origem  = normalizar_campo(voo, *campos_origem).upper()
        destino = normalizar_campo(voo, *campos_destino).upper()

        if origem != icao and destino != icao:
            continue

        empresa   = normalizar_campo(voo, *campos_empresa)
        nr_voo    = normalizar_campo(voo, *campos_voo)
        equip     = normalizar_campo(voo, *campos_equip)
        partida   = normalizar_campo(voo, *campos_partida)
        chegada   = normalizar_campo(voo, *campos_chegada)
        assentos  = normalizar_campo(voo, *campos_assento)
        tp_op     = normalizar_campo(voo, *campos_op)
        etapa     = normalizar_campo(voo, *campos_etapa)

        registro = {
            "callsign":          f"{empresa}{nr_voo}".strip() or "?",
            "numero_voo":        nr_voo,
            "airline_icao":      empresa,
            "airline":           get_airline_name(empresa),
            "equipamento_icao":  equip,
            "equipamento":       get_equipment_name(equip),
            "assentos":          assentos,
            "etapa":             etapa,
            "tipo_operacao":     TIPO_OPERACAO.get(tp_op.upper(), tp_op or "Domestico"),
            "origem_icao":       origem,
            "destino_icao":      destino,
            "partida_utc":       partida,
            "chegada_utc":       chegada,
            "partida_brt":       parse_datetime_brt(partida),
            "chegada_brt":       parse_datetime_brt(chegada),
            "status":            "programado",   # SIROS so tem voos planejados
            "fonte":             "SIROS/ANAC",
        }

        if destino == icao:
            registro["rota"] = origem
            chegadas.append(registro)

        if origem == icao:
            registro["rota"] = destino
            partidas.append(registro)

    # Ordena pelo horario de partida/chegada
    chegadas.sort(key=lambda x: x.get("chegada_brt") or "")
    partidas.sort(key=lambda x: x.get("partida_brt") or "")

    return chegadas, partidas


# ── Execucao principal ────────────────────────────────────────────────────────

os.makedirs("data", exist_ok=True)

# Busca todos os voos do dia uma unica vez
todos_voos = buscar_voos_do_dia()

if not todos_voos:
    print("\n[AVISO] Nenhum voo retornado pela API. Salvando arquivos vazios.")

# Processa cada aeroporto configurado
for icao in AIRPORTS:
    print(f"\nProcessando {icao}...")

    # Dados do aeroporto
    dados_aerodromo = buscar_dados_aerodromo(icao)
    nome_aerodromo  = (
        dados_aerodromo.get("nm_aerodromo")
        or dados_aerodromo.get("nome")
        or dados_aerodromo.get("name")
        or icao
    )

    chegadas, partidas = filtrar_e_normalizar(todos_voos, icao)
    print(f"  Filtrado: {len(chegadas)} chegadas, {len(partidas)} partidas")

    output = {
        "updated_at":     datetime.now(timezone.utc).isoformat(),
        "data_referencia": data_iso,
        "airport_icao":   icao,
        "airport_name":   nome_aerodromo,
        "airport_info":   dados_aerodromo,
        "source":         "SIROS/ANAC",
        "source_url":     "https://sas.anac.gov.br/sas/siros_api/",
        "arrivals":       chegadas,
        "departures":     partidas,
    }

    path = f"data/{icao}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    print(f"  Salvo em: {path}")

print("\nConcluido.")
