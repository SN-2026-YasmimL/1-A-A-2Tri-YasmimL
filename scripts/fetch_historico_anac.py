"""
fetch_historico_anac.py — Dados históricos ANAC/VRA + Supabase (v2 - URL corrigida)
Busca o arquivo VRA (Voo Regular Ativo) do portal de dados abertos da ANAC,
processa e insere na tabela historico_vra do Supabase.

Execução: mensal (1º dia de cada mês via GitHub Actions)

CORREÇÃO (2026-08): a ANAC descontinuou a publicação estática de arquivos
no formato antigo (.../VRA/{ano}/{ano}{mes}.csv) em outubro de 2024.
A nova estrutura de pastas é:
  Voos e operações aéreas/Voo Regular Ativo (VRA)/{ano}/{MM} - {NomeMês}/VRA_{ano}{mes_sem_zero}.csv

Exemplo confirmado manualmente:
  .../Voo Regular Ativo (VRA)/2026/07 - Julho/VRA_20267.csv

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

# Período: usa mês anterior por padrão (o VRA do mês atual só fica disponível
# depois do fechamento do mês)
BRT  = timezone(timedelta(hours=-3))
hoje = datetime.now(BRT)

if os.environ.get("ANO_MES"):
    ano_mes = os.environ["ANO_MES"].strip()  # ex: 2026-07
else:
    primeiro_do_mes = hoje.replace(day=1)
    mes_anterior    = primeiro_do_mes - timedelta(days=1)
    ano_mes         = mes_anterior.strftime("%Y-%m")

ano, mes = ano_mes.split("-")
mes_int  = int(mes)

print(f"Período histórico: {ano_mes}")
print(f"Aeroportos filtrados: {', '.join(AIRPORTS)}")

# ── URL do VRA (estrutura nova, confirmada em 2026-08) ────────────────────────

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}

nome_mes = MESES_PT[mes_int]

# Pasta usa mês COM zero à esquerda (ex: "07 - Julho")
# Nome do arquivo usa mês SEM zero à esquerda (ex: "VRA_20267.csv" para 2026-07)
BASE_PATH = (
    "https://sistemas.anac.gov.br/dadosabertos/"
    "Voos%20e%20opera%C3%A7%C3%B5es%20a%C3%A9reas/"
    "Voo%20Regular%20Ativo%20%28VRA%29/"
    f"{ano}/{mes_int:02d}%20-%20{nome_mes}/"
)
VRA_URL = f"{BASE_PATH}VRA_{ano}{mes_int}.csv"

print(f"URL alvo: {VRA_URL}")

# Mapeamento de colunas do CSV do VRA
# ATUALIZADO (2026-08): a ANAC reestruturou o layout do arquivo. Nomes antigos
# mantidos na lista por segurança/compatibilidade, mas os novos (confirmados
# no arquivo de 2026-07) vêm primeiro.
COLS = {
    "empresa":       ["ICAO Empresa Aérea", "EMPRESA (SIGLA)", "Empresa (Sigla)", "sg_empresa_icao"],
    "voo":           ["Número Voo", "NÚMERO VOO", "Numero Voo", "nr_voo"],
    "origem":        ["ICAO Aeródromo Origem", "ORIGEM", "Aeroporto Origem", "sg_icao_origem"],
    "destino":       ["ICAO Aeródromo Destino", "DESTINO", "Aeroporto Destino", "sg_icao_destino"],
    "partida_prev":  ["Partida Prevista", "PARTIDA PREVISTA", "dt_partida_prevista"],
    "partida_real":  ["Partida Real", "PARTIDA REAL", "dt_partida_real"],
    "chegada_prev":  ["Chegada Prevista", "CHEGADA PREVISTA", "dt_chegada_prevista"],
    "chegada_real":  ["Chegada Real", "CHEGADA REAL", "dt_chegada_real"],
    "situacao":      ["Situação Voo", "SITUAÇÃO DE VOO", "Situacao Voo", "situacao"],
    "motivo":        ["Código Justificativa", "MOTIVO", "Motivo Alteracao", "motivo_alteracao"],
    # "dt_ref" removido: essa coluna não existe mais no layout novo.
    # A data de referência agora é derivada da data de "Partida Prevista".
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


def registrar_execucao(
    periodo: str,
    aeroportos: list,
    voos_processados: int,
    lotes_enviados: int,
    erros: int,
    status: str,
    obs: str = "",
) -> None:
    """Grava o log de execução na tabela execucoes (mesmo formato usado pelo
    pipeline SIROS), para que o histórico apareça na aba Pipeline do painel."""
    try:
        db.table("execucoes").insert({
            "concluido_em":        datetime.now(timezone.utc).isoformat(),
            "aeroportos_buscados": aeroportos,
            "voos_processados":    voos_processados,
            "lotes_enviados":      lotes_enviados,
            "erros":               erros,
            "status":              status,
            "observacao":          obs or f"[historico_vra] período {periodo}",
        }).execute()
        print(f"\n  Log de execução salvo — status: {status}")
    except Exception as e:
        print(f"  [AVISO] Não foi possível salvar o log de execução: {e}")


# ── Busca o arquivo VRA ───────────────────────────────────────────────────────

def baixar_vra() -> list[dict]:
    print(f"\nGET {VRA_URL}")
    try:
        r = requests.get(VRA_URL, timeout=120)
        if r.status_code == 404:
            print("  [AVISO] Arquivo não encontrado (404) — pode não ter sido "
                  "publicado ainda, ou o nome do arquivo/pasta mudou de novo.")
            return []
        r.raise_for_status()
        # CORREÇÃO (2026-08): o arquivo VRA passou a ser publicado em UTF-8
        # (o formato antigo era latin-1). Usar utf-8-sig remove o BOM se presente.
        texto = r.content.decode("utf-8-sig", errors="replace")

        linhas_texto = texto.split("\n")

        # A ANAC passou a incluir uma linha de metadado
        # ("Atualizado em: AAAA-MM-DD") ANTES do cabeçalho real do CSV.
        if linhas_texto and (
            "atualizado em" in linhas_texto[0].lower()
            or linhas_texto[0].count(";") == 0
        ):
            print(f"  Descartando linha de metadado inicial: {linhas_texto[0]!r}")
            linhas_texto = linhas_texto[1:]

        texto_limpo = "\n".join(linhas_texto)

        # Detecta o delimitador automaticamente (';' era o padrão antigo,
        # mas a reestruturação do portal pode ter mudado para ',')
        primeira_linha = texto_limpo.split("\n", 1)[0]
        delimitador = ";" if primeira_linha.count(";") >= primeira_linha.count(",") else ","
        reader = csv.DictReader(io.StringIO(texto_limpo), delimiter=delimitador)
        registros = list(reader)
        print(f"  VRA carregado: {len(registros)} linhas brutas (delimitador='{delimitador}')")
        if registros:
            print(f"  Colunas encontradas no CSV: {list(registros[0].keys())}")
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
        partida_prev  = get_col(row, "partida_prev")
        partida_real  = get_col(row, "partida_real")
        chegada_prev  = get_col(row, "chegada_prev")
        chegada_real  = get_col(row, "chegada_real")
        situacao      = get_col(row, "situacao")
        motivo        = get_col(row, "motivo")

        # Data de referência: derivada da data de "Partida Prevista"
        # (a coluna dedicada DT_REFERENCIA não existe mais no layout novo)
        dt_ref = None
        if partida_prev:
            try:
                for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S"):
                    try:
                        dt_ref = datetime.strptime(partida_prev.strip(), fmt).date().isoformat()
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


# ── Execução principal ─────────────────────────────────────────────────────────

linhas_vra = baixar_vra()

if not linhas_vra:
    print("\n[AVISO] VRA não disponível para o período. Encerrando.")
    registrar_execucao(ano_mes, AIRPORTS, 0, 0, 0, "sem_dados",
                        "Arquivo VRA não encontrado ou vazio para o período.")
    sys.exit(0)

registros   = processar_vra(linhas_vra)

if not registros:
    print("\n[AVISO] Nenhum registro bateu com os aeroportos configurados. "
          "Isso pode indicar que os nomes das colunas do CSV mudaram — "
          "confira a lista de 'Colunas encontradas' impressa acima.")
    registrar_execucao(ano_mes, AIRPORTS, 0, 0, 0, "sem_dados",
                        "0 registros após filtro — possível mudança de layout do CSV.")
    sys.exit(0)

processados = 0
total_lotes = 0
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
        total_lotes += 1
        print(f"  Lote {num_lote}: {len(lote)} registros enviados/processados")
    except Exception as e:
        erros += 1
        print(f"  [ERRO] Lote {num_lote}: {e}")

if erros == 0:
    status_final = "concluido"
elif processados > 0:
    status_final = "erro_parcial"
else:
    status_final = "erro_critico"

obs = (
    f"Período: {ano_mes} | Aeroportos: {', '.join(AIRPORTS)} | "
    f"Processados: {processados} | Lotes: {total_lotes} | Erros: {erros}"
)

registrar_execucao(ano_mes, AIRPORTS, processados, total_lotes, erros, status_final, obs)

print(f"\nConcluído — {processados} registros históricos enviados/processados.")
if erros > 0:
    print(f"[ATENÇÃO] {erros} lote(s) com erro.")
    sys.exit(1)
