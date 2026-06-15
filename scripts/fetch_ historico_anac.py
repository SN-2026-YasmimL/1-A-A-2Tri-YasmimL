"""
fetch_historico_anac.py — Dados históricos ANAC/VRA + Supabase
Busca o arquivo VRA (Voo Regular Ativo) do portal de dados abertos da ANAC,
processa e insere na tabela historico_vra do Supabase.

Execução: mensal (1º dia de cada mês via GitHub Actions)

Variáveis de ambiente:
  SUPABASE_URL         → URL do projeto (GitHub Secret)
  SUPABASE_SERVICE_KEY → secret key / service_role key (GitHub Secret)
  AIRPORTS             → ICAOs para filtrar (GitHub Variable)
  ANO_MES              → Período a buscar no formato AAAA-MM
                         Padrão: mês anterior ao atual
"""

import csv
import io
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
    sys.exit(1)

db = create_client(SUPABASE_URL, SUPABASE_KEY)
print(f"Supabase conectado: {SUPABASE_URL}")

# ── Configurações ─────────────────────────────────────────────────────────────

airports_env = os.environ.get("AIRPORTS", "SBCA")
AIRPORTS     = [a.strip().upper() for a in airports_env.split(",") if a.strip()]
LOTE         = 500

# Período: usa mês anterior por padrão (o VRA do mês atual fica disponível
# somente após o fechamento do mês)
BRT  = timezone(timedelta(hours=-3))
hoje = datetime.now(BRT)

if os.environ.get("ANO_MES"):
    ano_mes = os.environ["ANO_MES"].strip()  # ex: 2026-04
else:
    primeiro_do_mes = hoje.replace(day=1)
    mes_anterior    = primeiro_do_mes - timedelta(days=1)
    ano_mes         = mes_anterior.strftime("%Y-%m")

ano, mes = ano_mes.split("-")

print(f"Período histórico: {ano_mes}")
print(f"Aeroportos filtrados: {', '.join(AIRPORTS)}")

# ── URL do VRA ────────────────────────────────────────────────────────────────
# Formato do portal ANAC:
# https://sistemas.anac.gov.br/dadosabertos/Voos%20e%20opera%C3%A7%C3%B5es/VRA/YYYY/AAAAMM.csv
VRA_URL = (
    f"https://sistemas.anac.gov.br/dadosabertos/"
    f"Voos%20e%20opera%C3%A7%C3%B5es/VRA/{ano}/{ano}{mes}.csv"
)

# URL alternativa (portal de dados abertos)
VRA_URL_ALT = (
    f"https://www.gov.br/anac/pt-br/assuntos/dados-e-estatisticas/"
    f"dados-estatisticos/arquivos/VRA{ano}{mes}.csv"
)

# Mapeamento de colunas do CSV do VRA
# (nomes reais no arquivo — podem variar levemente entre versões)
COLS = {
    "empresa":       ["EMPRESA (SIGLA)", "Empresa (Sigla)", "sg_empresa_icao"],
    "voo":           ["NÚMERO VOO",      "Numero Voo",      "nr_voo"],
    "origem":        ["ORIGEM",          "Aeroporto Origem","sg_icao_origem"],
    "destino":       ["DESTINO",         "Aeroporto Destino","sg_icao_destino"],
    "dt_ref":        ["DT_REFERENCIA",   "Dt Referencia",   "data_referencia"],
    "partida_prev":  ["PARTIDA PREVISTA","Partida Prevista", "dt_partida_prevista"],
    "partida_real":  ["PARTIDA REAL",    "Partida Real",    "dt_partida_real"],
    "chegada_prev":  ["CHEGADA PREVISTA","Chegada Prevista", "dt_chegada_prevista"],
    "chegada_real":  ["CHEGADA REAL",    "Chegada Real",    "dt_chegada_real"],
    "situacao":      ["SITUAÇÃO DE VOO", "Situacao Voo",    "situacao"],
    "motivo":        ["MOTIVO",          "Motivo Alteracao","motivo_alteracao"],
}


def get_col(row: dict, key: str) -> str:
    """Tenta múltiplos nomes de coluna para compatibilidade entre versões do CSV."""
    for nome in COLS.get(key, [key]):
        if nome in row:
            return (row[nome] or "").strip()
    return ""


def parse_dt_anac(dt_str: str) -> str | None:
    """Converte 'DD/MM/YYYY HH:MM' para ISO UTC."""
    if not dt_str or len(dt_str) < 16:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(dt_str.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def diff_minutos(partida_prev: str, partida_real: str) -> int | None:
    """Calcula atraso em minutos entre horário previsto e real."""
    try:
        fmt = "%d/%m/%Y %H:%M"
        dp  = datetime.strptime(partida_prev.strip(), fmt)
        dr  = datetime.strptime(partida_real.strip(), fmt)
        return int((dr - dp).total_seconds() / 60)
    except Exception:
        return None


# ── Busca o arquivo VRA ───────────────────────────────────────────────────────

def baixar_vra() -> list[dict]:
    for url in [VRA_URL, VRA_URL_ALT]:
        print(f"\nGET {url}")
        try:
            r = requests.get(url, timeout=120)
            if r.status_code == 404:
                print(f"  Não encontrado (404) — tentando URL alternativa.")
                continue
            r.raise_for_status()
            # Decodifica com latin-1 (padrão do VRA)
            texto = r.content.decode("latin-1", errors="replace")
            reader = csv.DictReader(io.StringIO(texto), delimiter=";")
            registros = list(reader)
            print(f"  VRA carregado: {len(registros)} linhas brutas")
            return registros
        except Exception as e:
            print(f"  [ERRO] {e}")
    return []


# ── Processa e filtra registros ───────────────────────────────────────────────

def processar_vra(linhas: list[dict]) -> list[dict]:
    resultado = []
    for row in linhas:
        origem  = get_col(row, "origem").upper()
        destino = get_col(row, "destino").upper()
        if origem not in AIRPORTS and destino not in AIRPORTS:
            continue

        empresa       = get_col(row, "empresa")
        nr_voo        = get_col(row, "voo")
        dt_ref_str    = get_col(row, "dt_ref")
        partida_prev  = get_col(row, "partida_prev")
        partida_real  = get_col(row, "partida_real")
        chegada_prev  = get_col(row, "chegada_prev")
        chegada_real  = get_col(row, "chegada_real")
        situacao      = get_col(row, "situacao")
        motivo        = get_col(row, "motivo")

        # Data de referência
        dt_ref = None
        if dt_ref_str:
            try:
                for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                    try:
                        dt_ref = datetime.strptime(dt_ref_str.strip(), fmt).date().isoformat()
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

        resultado.append({
            "ano_mes":          ano_mes,
            "icao_empresa":     empresa or None,
            "nr_voo":           nr_voo or None,
            "icao_origem":      origem or None,
            "icao_destino":     destino or None,
            "dt_referencia":    dt_ref,
            "partida_real":     parse_dt_anac(partida_real),
            "chegada_real":     parse_dt_anac(chegada_real),
            "atraso_partida":   diff_minutos(partida_prev, partida_real),
            "atraso_chegada":   diff_minutos(chegada_prev, chegada_real),
            "situacao":         situacao.lower() if situacao else None,
            "motivo_alteracao": motivo or None,
        })

    print(f"  Registros filtrados para os aeroportos configurados: {len(resultado)}")
    return resultado


# ── Inserção no Supabase ──────────────────────────────────────────────────────

linhas_vra  = baixar_vra()
if not linhas_vra:
    print("\n[AVISO] VRA não disponível para o período. Encerrando.")
    sys.exit(0)

registros   = processar_vra(linhas_vra)
processados = 0
erros       = 0

for i in range(0, len(registros), LOTE):
    lote     = registros[i:i + LOTE]
    num_lote = i // LOTE + 1
    try:
        db.table("historico_vra").upsert(
            lote,
            on_conflict="ano_mes,icao_empresa,nr_voo,icao_origem,icao_destino,dt_referencia",
        ).execute()
        processados += len(lote)
        print(f"  Lote {num_lote}: {len(lote)} registros enviados/processados")
    except Exception as e:
        erros += 1
        print(f"  [ERRO] Lote {num_lote}: {e}")

print(f"\nConcluído — {processados} registros históricos enviados/processados.")
if erros > 0:
    print(f"[ATENÇÃO] {erros} lote(s) com erro.")
    sys.exit(1)
