import streamlit as st
import pandas as pd
import zipfile
import io
import os
import re
from difflib import SequenceMatcher

# --- CONFIGURAÇÃO ---
st.set_page_config(layout="wide", page_title="Processador Horizon")
st.markdown("""
<style>
    .status-container { padding: 10px; border-radius: 5px; margin-bottom: 5px; font-weight: bold; text-align: center; }
    .status-on { background-color: #28a745; color: white; }
    .status-off { background-color: #dc3545; color: white; }
    .report-block { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #dee2e6; }
</style>
""", unsafe_allow_html=True)
st.title("PROCESSAMENTO DE DADOS: HORIZON")

if 'task_map' not in st.session_state:
    st.session_state.task_map = {}
if 'turbinas_removidas' not in st.session_state:
    st.session_state.turbinas_removidas = []
if 'vinculos_confirmados' not in st.session_state:
    st.session_state.vinculos_confirmados = {}
if 'turbinas_horizon_originais' not in st.session_state:
    st.session_state.turbinas_horizon_originais = []
if 'turbinas_horizon_removidas' not in st.session_state:
    st.session_state.turbinas_horizon_removidas = []


# ==============================================================================
# MAPEAMENTO ARTHWIND → SKYSPECS
# ==============================================================================

MAPPING = {
    # --- SURFACE ---
    "contaminated layer":   {"Component": "Blade", "Material": "Surface",    "Type": "Discoloration",  "Subtype": "Other"},
    "dirt /contamination":  {"Component": "Blade", "Material": "Surface",    "Type": "Discoloration",  "Subtype": "Mechanical (Oil)"},
    "dirt":                 {"Component": "Blade", "Material": "Surface",    "Type": "Discoloration",  "Subtype": "Mechanical (Oil)"},
    "oxidation":            {"Component": "Blade", "Material": "Surface",    "Type": "Discoloration",  "Subtype": "Other"},
    "fungi":                {"Component": "Blade", "Material": "Surface",    "Type": "Discoloration",  "Subtype": "Other"},
    "depression":           {"Component": "Blade", "Material": "Surface",    "Type": "None",           "Subtype": "None"},
    "resin excess":         {"Component": "Blade", "Material": "Surface",    "Type": "None",           "Subtype": "None"},
    "foreign object":       {"Component": "Blade", "Material": "Surface",    "Type": "Foreign Object", "Subtype": "None"},
    "gap":                  {"Component": "Blade", "Material": "Surface",    "Type": "Core Gap",       "Subtype": "None"},
    "step in upstand":      {"Component": "Blade", "Material": "Surface",    "Type": "Delamination",   "Subtype": "Wrinkle"},
    # --- LAMINATE ---
    "bubbles":              {"Component": "Blade", "Material": "Laminate",   "Type": "Air Inclusion",  "Subtype": "Other"},
    "microbubbles":         {"Component": "Blade", "Material": "Laminate",   "Type": "Air Inclusion",  "Subtype": "Other"},
    "semi dry glass":       {"Component": "Blade", "Material": "Laminate",   "Type": "Delamination",   "Subtype": "Dry Glass"},
    "dry glass":            {"Component": "Blade", "Material": "Laminate",   "Type": "Delamination",   "Subtype": "Dry Glass"},
    "wrinkle":              {"Component": "Blade", "Material": "Laminate",   "Type": "Delamination",   "Subtype": "Wrinkle"},
    "step":                 {"Component": "Blade", "Material": "Laminate",   "Type": "Delamination",   "Subtype": "Wrinkle"},
    "folded layer":         {"Component": "Blade", "Material": "Laminate",   "Type": "Delamination",   "Subtype": "Wrinkle"},
    "damaged layer":        {"Component": "Blade", "Material": "Laminate",   "Type": "Delamination",   "Subtype": "None"},
    "improper repair":      {"Component": "Blade", "Material": "Laminate",   "Type": "Delamination",   "Subtype": "Old Repair"},
    # --- STRUCTURE ---
    "delamination":                         {"Component": "Blade", "Material": "Structure", "Type": "Delamination", "Subtype": "None"},
    "root upstand delamination":            {"Component": "Blade", "Material": "Structure", "Type": "Delamination", "Subtype": "None"},
    "missing layer":                        {"Component": "Blade", "Material": "Structure", "Type": "Delamination", "Subtype": "None"},
    "holes in laminate":                    {"Component": "Blade", "Material": "Structure", "Type": "Delamination", "Subtype": "None"},
    "lightning strike":                     {"Component": "Blade", "Material": "Structure", "Type": "Delamination", "Subtype": "Lightning"},
    "crack in the laminate":                {"Component": "Blade", "Material": "Structure", "Type": "Crack",        "Subtype": "T-l-c Shaped"},
    "crack in the laminate longitudinal":   {"Component": "Blade", "Material": "Structure", "Type": "Crack",        "Subtype": "Longitudinal"},
    "crack in the laminate transversal":    {"Component": "Blade", "Material": "Structure", "Type": "Crack",        "Subtype": "Transverse"},
    "te insert crack":                      {"Component": "Blade", "Material": "Structure", "Type": "Crack",        "Subtype": "Longitudinal"},
    "crack around receptor":                {"Component": "Blade", "Material": "Structure", "Type": "Crack",        "Subtype": "Longitudinal"},
    "core contamination":                   {"Component": "Blade", "Material": "Structure", "Type": "Balsa Rot",    "Subtype": None},
    "core material damaged":                {"Component": "Blade", "Material": "Structure", "Type": "Balsa Rot",    "Subtype": None},
    "damaged core":                         {"Component": "Blade", "Material": "Structure", "Type": "Balsa Rot",    "Subtype": None},
    # --- BONDLINE ---
    "bonding paste failure":    {"Component": "Blade", "Material": "Bondline", "Type": "Bondline Failure", "Subtype": "None"},
    "crack in the bonding line":{"Component": "Blade", "Material": "Bondline", "Type": "Crack",            "Subtype": "Transverse",
                                 "alternativas": [{"Subtype": "Longitudinal"}]},
    # --- LPS ---
    "lps disconnected/damaged": {
        "Component": "Lightning Protection System", "Material": "Auxiliary Component",
        "Type": "LPS Cable", "Subtype": "None",
        "_subtype_by_severity": {"2": "None", "4": "Disconnected"},
        "_flag_severity": ["3"]
    },
    "absence of the lps card":  {"Component": "Lightning Protection System", "Material": "Auxiliary Component", "Type": "LPS Cable",      "Subtype": "None"},
    "lps connections":          {"Component": "Lightning Protection System", "Material": "Auxiliary Component", "Type": "Lug Connector",   "Subtype": "Disconnected"},
    "lps receptor missing":     {"Component": "Lightning Receptors",         "Material": "Auxiliary Component", "Type": "Missing",         "Subtype": "None"},
    "metallic tip missing":     {"Component": "Lightning Receptors",         "Material": "Auxiliary Component", "Type": "Missing",         "Subtype": "None"},
    "check lps receptor":       {"Component": "Other",                       "Material": "Auxiliary Component", "Type": "Other",           "Subtype": "None"},
    # --- ROOT / CLOSEOUT ---
    "close out sealant damaged":    {"Component": "Root Closeout", "Material": "Auxiliary Component", "Type": "Circumference Debonding", "Subtype": "None"},
    "absence of close out cover":   {"Component": "Root Closeout", "Material": "Auxiliary Component", "Type": "Damaged Or Misaligned",   "Subtype": "None"},
    # --- PITCH SYSTEM ---
    "gap in the root insert":   {"Component": "Pitch System",    "Material": "Auxiliary Component", "Type": "Bolts", "Subtype": "None"},
    "missing stud":             {"Component": "Pitch System",    "Material": "Auxiliary Component", "Type": "Bolts", "Subtype": "None"},
    # --- SEALS / DRAINAGE ---
    "sealant damaged":          {"Component": "Seals",           "Material": "Auxiliary Component", "Type": "None",                  "Subtype": "None"},
    "drain hole obstructed":    {"Component": "Drainage System", "Material": "Auxiliary Component", "Type": "Damaged Or Obstructed", "Subtype": "None"},
    # --- HUB ---
    "damaged studs":            {"Component": "Hub",   "Material": "Auxiliary Component", "Type": "Other", "Subtype": None},
    # --- OTHER ---
    "damaged accessory":        {"Component": "Other", "Material": "Auxiliary Component", "Type": "Other", "Subtype": "None"},
    # --- CHECK POINTS (excluídos do output) ---
    "check point":      {"Component": "Other", "Material": "Auxiliary Component", "Type": "Other", "Subtype": "None", "_is_checkpoint": True},
    "check close poi":  {"Component": "Other", "Material": "Auxiliary Component", "Type": "Other", "Subtype": "None", "_is_checkpoint": True},
    "check damage":     {"Component": "Other", "Material": "Auxiliary Component", "Type": "Other", "Subtype": "None", "_is_checkpoint": True},
    "check delete":     {"Component": "Other", "Material": "Auxiliary Component", "Type": "Other", "Subtype": "None", "_is_checkpoint": True},
    "check repair done":{"Component": "Other", "Material": "Auxiliary Component", "Type": "Other", "Subtype": "None", "_is_checkpoint": True},
}

SKYSPECS_COLUMNS = [
    "Photo File Name", "Date", "Component", "Material", "Type", "Subtype",
    "Damage Location", "Blade Side", "Severity", "Width (m)", "Length (m)",
    "Distance (m)", "Coordinates"
]


def _remap_severity(sky_type, sky_material, sev_str, width_str, subtype=""):
    """Converte severidade Arthwind → SkySpecs. Retorna (nova_sev, nota)."""
    try:
        sev = int(sev_str)
    except (ValueError, TypeError):
        return sev_str, ""
    # Discoloration Mec.Oil → sempre Sev 2, inclusive quando sev original é 0
    if sky_type == "Discoloration" and subtype == "Mechanical (Oil)":
        if sev != 2:
            return "2", f"Sev convertida Discoloration Mec.Oil: {sev}→2"
        return sev_str, ""
    if sev == 0:
        return sev_str, ""
    if sky_type == "Bondline Failure":
        try:
            w_cm = float(width_str) * 100
        except (ValueError, TypeError):
            return sev_str, "ALERTA: largura inválida para Bondline Failure"
        new_sev = 4 if w_cm <= 25 else 5
        return str(new_sev), f"Sev recalculada por largura ({w_cm:.1f}cm): {sev}→{new_sev}"
    if sky_type == "Delamination":
        if sev == 2:
            return "3", "Sev convertida Delamination: 2→3"
        return sev_str, ""
    if sky_type == "Crack" and sky_material == "Structure":
        remap = {3: 4, 4: 4, 5: 5}
        if sev in remap:
            new_sev = remap[sev]
            nota = f"Sev convertida Crack: {sev}→{new_sev}" if new_sev != sev else ""
            return str(new_sev), nota
        return sev_str, ""
    return sev_str, ""


def _damage_location(filename):
    fu = filename.upper()
    if fu.startswith("PFII") or fu.startswith("TAC"):
        return "Internal"
    return "VERIFICAR"


def convert_damages_df(df, filename):
    """
    Converte DataFrame no formato Arthwind para o schema SkySpecs.
    Remove Check Points. Retorna DataFrame convertido + lista de flags.
    """
    output_rows = []
    flags_report = []

    for _, row in df.iterrows():
        arthwind_type = str(row.get("Type", "")).strip()
        key = arthwind_type.lower()
        map_entry = MAPPING.get(key)

        flag = ""
        is_checkpoint = False

        if map_entry:
            component     = map_entry["Component"]
            material      = map_entry["Material"]
            sky_type      = map_entry["Type"]
            subtype       = map_entry.get("Subtype")
            is_checkpoint = map_entry.get("_is_checkpoint", False)
            severity_val  = str(row.get("Severity", "")).strip()

            if "_subtype_by_severity" in map_entry:
                sev_map   = map_entry["_subtype_by_severity"]
                flag_sevs = map_entry.get("_flag_severity", [])
                if severity_val in sev_map:
                    subtype = sev_map[severity_val]
                    if severity_val in flag_sevs:
                        flag = f"ALERTA: Sev {severity_val} — subtype ambíguo, revisar manualmente"
                else:
                    flag = f"ALERTA: LPS Sev {severity_val} sem regra definida — subtype padrão aplicado"

            subtype_out = subtype if subtype is not None else ""

            if "alternativas" in map_entry:
                alt_list = [a.get("Subtype", "?") for a in map_entry["alternativas"]]
                flag = f"ALERTA: Subtype ambíguo — alternativas: {', '.join(str(a) for a in alt_list)}"
        else:
            component   = str(row.get("Component", ""))
            material    = str(row.get("Material", ""))
            sky_type    = arthwind_type
            subtype_out = str(row.get("Subtype", ""))
            flag = f"ERRO: Tipo '{arthwind_type}' não encontrado no mapeamento — revisar manualmente"

        severity_orig = str(row.get("Severity", "")).strip()
        if severity_orig == "0" and not is_checkpoint:
            flag = (flag + " | " if flag else "") + "ALERTA: Severidade 0 em registro que não é Check Point"

        severity_final, sev_nota = _remap_severity(
            sky_type, material, severity_orig, str(row.get("Width", "0")), subtype_out
        )
        if sev_nota:
            flag = (flag + " | " if flag else "") + sev_nota

        if is_checkpoint:
            continue

        if flag:
            flags_report.append({
                "Arquivo": filename,
                "Foto": str(row.get("Photo File Name", "")),
                "Tipo original": arthwind_type,
                "FLAG": flag,
            })

        output_rows.append({
            "Photo File Name": str(row.get("Photo File Name", "")),
            "Date":            str(row.get("Date", "")),
            "Component":       component,
            "Material":        material,
            "Type":            sky_type,
            "Subtype":         subtype_out,
            "Damage Location": _damage_location(filename),
            "Blade Side":      str(row.get("Blade Side", "")),
            "Severity":        severity_final,
            "Width (m)":       str(row.get("Width", "")),
            "Length (m)":      str(row.get("Length", "")),
            "Distance (m)":    str(row.get("Distance", "")),
            "Coordinates":     str(row.get("Coordinates", "")),
        })

    # FLAG não vai para o CSV de saída — apenas para o relatório de alertas
    df_out = pd.DataFrame(output_rows, columns=SKYSPECS_COLUMNS) if output_rows else pd.DataFrame(columns=SKYSPECS_COLUMNS)
    return df_out, flags_report


# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================

def clean_filename(name):
    if pd.isna(name): return ""
    return os.path.basename(str(name).strip().replace('"', '').replace("'", "")).lower()


def load_csv_robust(uploaded_file, is_damage=False):
    if uploaded_file is None: return None
    try:
        content = uploaded_file.getvalue().decode('utf-8', errors='ignore')
        lines = [l for l in content.splitlines() if l.strip()]
        if not lines: return None
        first_line = lines[0]
        sep = ',' if is_damage else (';' if first_line.count(';') > first_line.count(',') else ',')
        header = [h.strip().replace('"', '') for h in first_line.split(sep)]
        data = []
        for line in lines[1:]:
            parts = line.split(sep)
            if is_damage and len(parts) > len(header):
                fixed = parts[:len(header)-1]
                coords = ",".join(parts[len(header)-1:]).strip().strip('"')
                if coords.startswith('[[') and coords.endswith(']]'):
                    coords = coords[1:-1]
                fixed.append(coords)
                data.append(fixed)
            else:
                data.append([p.strip().strip('"') for p in parts[:len(header)]])
        return pd.DataFrame(data, columns=header)
    except Exception as e:
        st.error(f"Erro no processamento: {e}")
        return None


def load_horizon_base(uploaded_file):
    if uploaded_file is None: return None
    try:
        content = uploaded_file.getvalue().decode('utf-8', errors='ignore')
        lines = [l for l in content.splitlines() if l.strip()]
        if not lines: return None
        header_line = lines[0]
        sep = ';' if header_line.count(';') > header_line.count(',') else ','
        header = [h.strip().replace('"', '') for h in header_line.split(sep)]
        skip_keywords = ['delete this row', 'explanation:', 'valid data options']
        data = []
        for line in lines[1:]:
            first_field = line.split(sep)[0].strip().strip('"').lower()
            if any(kw in first_field for kw in skip_keywords):
                continue
            parts = line.split(sep)
            data.append([p.strip().strip('"') for p in parts[:len(header)]])
        df = pd.DataFrame(data, columns=header)
        if 'Notes' in df.columns:
            df = df.drop(columns=['Notes'])
        df = df[df.apply(lambda row: any(v.strip() != '' for v in row.astype(str)), axis=1)]
        return df
    except Exception as e:
        st.error(f"Erro ao carregar base Horizon: {e}")
        return None


def sugerir_match(nome_horizon, opcoes_atw):
    def normalizar(s):
        s = s.lower()
        s = re.sub(r'[-_\s]', '', s)
        s = re.sub(r'0+(\d)', r'\1', s)
        return s
    nome_norm = normalizar(nome_horizon)
    melhor_score = -1
    melhor_opcao = opcoes_atw[0] if opcoes_atw else None
    for opcao in opcoes_atw:
        score = SequenceMatcher(None, nome_norm, normalizar(opcao)).ratio()
        if score > melhor_score:
            melhor_score = score
            melhor_opcao = opcao
    return melhor_opcao, melhor_score


def deduplicate_atw(df):
    if df is None or 'Turbine' not in df.columns:
        return df, 0
    total_antes = len(df)
    df_dedup = df.drop_duplicates(subset='Turbine', keep='first').reset_index(drop=True)
    return df_dedup, total_antes - len(df_dedup)


# ==============================================================================
# SIDEBAR
# ==============================================================================

st.sidebar.header("STATUS DOS ARQUIVOS")

def check_status(file, name):
    if file:
        st.sidebar.markdown(f'<div class="status-container status-on">✓ {name}</div>', unsafe_allow_html=True)
        return True
    st.sidebar.markdown(f'<div class="status-container status-off">✗ {name}</div>', unsafe_allow_html=True)
    return False


# ==============================================================================
# INPUTS
# ==============================================================================

c1, c2 = st.columns([1, 2])
with c1:
    st.markdown('<div class="report-block">', unsafe_allow_html=True)
    st.subheader("1. REFERÊNCIA (MESTRE)")
    f_horizon = st.file_uploader("Base Horizon (summary_base)", type=['csv'])
    h_ok = check_status(f_horizon, "HORIZON")
    if f_horizon:
        try:
            df_hor_base = load_horizon_base(f_horizon)
            if df_hor_base is not None and 'Turbine' in df_hor_base.columns:
                st.session_state.task_map = (
                    df_hor_base
                    .drop_duplicates('Turbine')
                    .set_index('Turbine')[['Horizon Task ID', 'Site']]
                    .to_dict('index')
                )
                st.session_state.turbinas_horizon_originais = sorted(
                    df_hor_base['Turbine'].dropna().unique().tolist()
                )
                for th, ta in st.session_state.vinculos_confirmados.items():
                    if th in st.session_state.task_map:
                        st.session_state.task_map[ta] = st.session_state.task_map[th]
        except: pass
    st.markdown('</div>', unsafe_allow_html=True)

with c2:
    st.markdown('<div class="report-block">', unsafe_allow_html=True)
    st.subheader("2. DADOS INSPEÇÃO")
    f_sum = st.file_uploader("Summary ATW", type=['csv'])
    s_ok = check_status(f_sum, "SUMMARY ATW")
    f_det = st.file_uploader("Details", type=['csv'])
    d_ok = check_status(f_det, "DETAILS")
    f_dam_list = st.file_uploader("Damages (Lote)", type=['csv'], accept_multiple_files=True)
    m_ok = check_status(f_dam_list, "DAMAGES")
    st.markdown('</div>', unsafe_allow_html=True)


# --- DEDUPLICAÇÃO DO ATW ---
df_atw_dedup = None
if s_ok:
    df_atw_raw = load_csv_robust(f_sum)
    if df_atw_raw is not None and 'Turbine' in df_atw_raw.columns:
        df_atw_dedup, n_duplicatas = deduplicate_atw(df_atw_raw)
        if n_duplicatas > 0:
            st.warning(
                f"⚠️ O Summary ATW continha **{n_duplicatas} linha(s) duplicada(s)**. "
                f"Foram removidas automaticamente, mantendo a primeira ocorrência de cada turbina."
            )


# ==============================================================================
# VALIDAÇÃO DE NOMENCLATURA
# ==============================================================================

pode_forjar = False
if h_ok and s_ok and df_atw_dedup is not None:
    st.markdown('<div class="report-block">', unsafe_allow_html=True)
    st.subheader("3. VALIDAÇÃO DE NOMENCLATURA")
    turbinas_atw = sorted([t for t in df_atw_dedup['Turbine'].unique() if t and str(t).strip() != ''])
    turbinas_hor = sorted([
        t for t in (st.session_state.turbinas_horizon_originais or st.session_state.task_map.keys())
        if t and str(t).strip() != ''
    ])
    set_atw = set(turbinas_atw)
    set_hor = set(turbinas_hor)
    vinculos = st.session_state.vinculos_confirmados
    set_hor_mapeado = set(vinculos.values())
    set_hor_sem_vinculo = set_hor - set(vinculos.keys())
    extras    = sorted(set_atw - set_hor - set_hor_mapeado)
    faltantes = sorted(set_hor_sem_vinculo - set_atw)

    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Turbinas na Horizon", len(turbinas_hor))
    cc2.metric("Turbinas no Summary ATW", len(turbinas_atw))
    delta = len(turbinas_atw) - len(turbinas_hor)
    cc3.metric("Diferença (ATW − Horizon)", delta, delta_color="inverse")
    st.divider()

    removidas = st.session_state.turbinas_removidas
    if extras:
        st.warning(f"⚠️ {len(extras)} turbina(s) no ATW mas **ausente(s) na Horizon**: {', '.join(extras)}")
        remover = st.multiselect(
            "Selecione as turbinas EXTRAS para REMOVER do pacote:",
            options=extras,
            default=[e for e in extras if e not in removidas],
            key="extras_remover"
        )
        if st.button("CONFIRMAR REMOÇÃO"):
            st.session_state.turbinas_removidas = list(set(removidas) | set(remover))
            st.rerun()
        removidas = st.session_state.turbinas_removidas
        ainda_extras = [e for e in extras if e not in removidas]
        if ainda_extras:
            st.error(f"❌ Ainda há {len(ainda_extras)} turbina(s) extra(s): {', '.join(ainda_extras)}")
        else:
            if removidas:
                st.success(f"✅ {len([e for e in removidas if e in extras])} turbina(s) extra(s) removida(s).")

    if faltantes:
        st.warning(f"⚠️ {len(faltantes)} turbina(s) da Horizon **ausente(s) no ATW**: {', '.join(faltantes)}")
        removidas_set = set(st.session_state.turbinas_removidas)
        hor_removidas = set(st.session_state.turbinas_horizon_removidas)
        ja_vinculadas = set(vinculos.values())
        opcoes_atw = sorted(set_atw - removidas_set - ja_vinculadas)
        para_remover_hor = st.multiselect(
            "Turbinas da Horizon **sem inspeção** — selecione as que deseja REMOVER:",
            options=faltantes,
            default=[t for t in faltantes if t in hor_removidas],
            key="hor_remover"
        )
        para_vincular = [t for t in faltantes if t not in para_remover_hor]
        if st.button("CONFIRMAR REMOÇÃO DA HORIZON", key="btn_hor_remover"):
            st.session_state.turbinas_horizon_removidas = para_remover_hor
            st.rerun()
        hor_removidas = set(st.session_state.turbinas_horizon_removidas)
        para_vincular = [t for t in faltantes if t not in hor_removidas]
        if para_vincular:
            if opcoes_atw:
                correcoes = {}
                cv1, cv2 = st.columns(2)
                for i, th in enumerate(para_vincular):
                    with cv1 if i % 2 == 0 else cv2:
                        sugerido, score = sugerir_match(th, opcoes_atw)
                        default_idx = opcoes_atw.index(sugerido) if sugerido in opcoes_atw else 0
                        label_score = f" ({score:.0%} similar)" if score < 1.0 else " (idêntico)"
                        sel = st.selectbox(
                            f"Vincular '{th}' (Horizon) a: — sugestão: **{sugerido}**{label_score}",
                            options=opcoes_atw, index=default_idx, key=f"v_{th}"
                        )
                        correcoes[th] = sel
                if st.button("CONFIRMAR VÍNCULOS"):
                    for th, ta in correcoes.items():
                        if th in st.session_state.task_map:
                            st.session_state.task_map[ta] = st.session_state.task_map[th]
                    st.session_state.vinculos_confirmados.update(correcoes)
                    st.rerun()
            else:
                st.error("❌ Não há turbinas disponíveis no ATW para vincular.")

    if vinculos:
        with st.expander(f"🔗 {len(vinculos)} vínculo(s) confirmado(s)", expanded=False):
            for th, ta in vinculos.items():
                st.markdown(f"- **{th}** (Horizon) → **{ta}** (ATW)")

    removidas_final     = set(st.session_state.turbinas_removidas)
    hor_removidas_final = set(st.session_state.turbinas_horizon_removidas)
    ainda_extras_final  = [e for e in (set_atw - set_hor - set(vinculos.values())) if e not in removidas_final]
    faltantes_final     = sorted(set_hor - set(vinculos.keys()) - set_atw - hor_removidas_final)

    if hor_removidas_final:
        st.success(f"✅ {len(hor_removidas_final)} turbina(s) da Horizon removida(s): {', '.join(sorted(hor_removidas_final))}")
    if not faltantes_final and not ainda_extras_final:
        st.success("✅ Dados completos para as turbinas solicitadas pela Horizon.")
        pode_forjar = True
    st.markdown('</div>', unsafe_allow_html=True)


# ==============================================================================
# VERIFICAÇÃO DE REQUISITOS HORIZON
# ==============================================================================

INSPECTION_TYPES_VALIDOS = [
    "Autonomous Drone", "Blade External Other", "Blade Internal",
    "Gearbox Borescope", "Generic", "Ground Photo", "Manual Drone",
    "Rope Inspection", "Tower External", "Transition Piece"
]

erros_criticos = []
avisos = []

if s_ok and d_ok and m_ok and pode_forjar:
    st.markdown('<div class="report-block">', unsafe_allow_html=True)
    st.subheader("4. VERIFICAÇÃO DE REQUISITOS HORIZON")

    with st.expander("📄 Summary", expanded=True):
        df_chk_s = df_atw_dedup.copy() if df_atw_dedup is not None else None
        if df_chk_s is not None:
            removidas_set = set(st.session_state.turbinas_removidas)
            df_chk_s = df_chk_s[~df_chk_s['Turbine'].isin(removidas_set)]
            date_col = next((c for c in df_chk_s.columns if 'date' in c.lower() or 'data' in c.lower()), None)
            if date_col is None:
                st.error("❌ Coluna de data não encontrada")
                erros_criticos.append("Summary: coluna de data não encontrada")
            else:
                sample = df_chk_s[date_col].dropna().head(20)
                formato_br = sample.apply(lambda x: bool(re.match(r'^\d{2}/\d{2}/\d{4}$', str(x))) and int(str(x).split('/')[0]) > 12).any()
                ambiguo    = sample.apply(lambda x: bool(re.match(r'^\d{2}/\d{2}/\d{4}$', str(x))) and int(str(x).split('/')[0]) <= 12).any()
                if formato_br:
                    st.warning("⚠️ Datas em formato BR (dd/mm/yyyy) — serão convertidas para mm/dd/yyyy")
                    avisos.append("Summary: datas em formato BR serão convertidas")
                elif ambiguo:
                    st.warning("⚠️ Datas com formato ambíguo — verifique se estão em mm/dd/yyyy")
                    avisos.append("Summary: datas ambíguas detectadas")
                else:
                    st.success(f"✅ Formato de data OK ({date_col})")
            if 'Inspection Type' in df_chk_s.columns:
                invalidos = df_chk_s[~df_chk_s['Inspection Type'].isin(INSPECTION_TYPES_VALIDOS)]['Inspection Type'].unique()
                invalidos = [v for v in invalidos if v and str(v).strip() != '']
                if invalidos:
                    st.error(f"❌ Inspection Type inválido(s): {', '.join(invalidos)}")
                    erros_criticos.append(f"Summary: Inspection Type inválido — {', '.join(invalidos)}")
                else:
                    st.success("✅ Inspection Type OK")
            else:
                st.error("❌ Coluna 'Inspection Type' não encontrada")
                erros_criticos.append("Summary: coluna Inspection Type não encontrada")

    with st.expander("📄 Details", expanded=True):
        df_chk_d = load_csv_robust(f_det)
        if df_chk_d is not None:
            idc = 'ID' if 'ID' in df_chk_d.columns else df_chk_d.columns[0]
            nomes_atw_chk = set(st.session_state.vinculos_confirmados.values())
            valid_set_chk = (set(st.session_state.task_map.keys()) | nomes_atw_chk) - set(st.session_state.turbinas_removidas)
            df_chk_d = df_chk_d[df_chk_d[idc].isin(valid_set_chk)]
            path_col = next(
                (c for c in df_chk_d.columns if c.lower() == 'path'),
                next((c for c in df_chk_d.columns if any(x in c.lower() for x in ['file', 'image']) and 'url' not in c.lower()), None)
            )
            url_col = next((c for c in df_chk_d.columns if 'url' in c.lower()), None)
            if path_col:
                vazios = df_chk_d[path_col].isna().sum() + (df_chk_d[path_col] == '').sum()
                if vazios > 0:
                    st.error(f"❌ {vazios} linha(s) sem Path ({path_col})")
                    erros_criticos.append(f"Details: {vazios} linha(s) sem Path")
                else:
                    st.success(f"✅ Path OK ({path_col})")
            else:
                st.warning("⚠️ Coluna de Path/File não identificada")
                avisos.append("Details: coluna de path não identificada")
            if url_col:
                vazios_url = df_chk_d[url_col].isna().sum() + (df_chk_d[url_col] == '').sum()
                if vazios_url > 0:
                    st.error(f"❌ {vazios_url} linha(s) sem URL ({url_col})")
                    erros_criticos.append(f"Details: {vazios_url} linha(s) sem URL")
                else:
                    st.success(f"✅ URL OK ({url_col})")
            else:
                st.warning("⚠️ Coluna de URL não identificada")
                avisos.append("Details: coluna de URL não identificada")
            rad_col = next((c for c in df_chk_d.columns if 'radial' in c.lower() or 'distance' in c.lower()), None)
            if rad_col:
                nao_numerico = df_chk_d[pd.to_numeric(df_chk_d[rad_col], errors='coerce').isna() & df_chk_d[rad_col].notna() & (df_chk_d[rad_col] != '')].shape[0]
                if nao_numerico > 0:
                    st.error(f"❌ {nao_numerico} valor(es) não numérico(s) em Radial Distance")
                    erros_criticos.append(f"Details: {nao_numerico} valor(es) não numérico(s) em Radial Distance")
                else:
                    st.success(f"✅ Radial Distance OK ({rad_col})")
            else:
                st.warning("⚠️ Coluna de Radial Distance não identificada")
                avisos.append("Details: coluna de Radial Distance não identificada")

    with st.expander("📄 Damages (pré-conversão)", expanded=True):
        coord_pattern = re.compile(r'^(\[\d+,\s*\d+\],?\s*)+$')
        for f_dam in f_dam_list:
            df_chk_m = load_csv_robust(f_dam, is_damage=True)
            if df_chk_m is not None:
                st.markdown(f"**{f_dam.name}**")
                if 'Photo File Name' in df_chk_m.columns:
                    vazios_foto = df_chk_m['Photo File Name'].isna().sum() + (df_chk_m['Photo File Name'] == '').sum()
                    if vazios_foto > 0:
                        st.error(f"❌ {vazios_foto} linha(s) sem Photo File Name")
                        erros_criticos.append(f"Damages ({f_dam.name}): {vazios_foto} linha(s) sem Photo File Name")
                    else:
                        st.success("✅ Photo File Name preenchido")
                if 'Coordinates' in df_chk_m.columns:
                    coord_invalidas = df_chk_m['Coordinates'].dropna().apply(
                        lambda x: not bool(coord_pattern.match(str(x).strip())) if str(x).strip() != '' else False
                    ).sum()
                    if coord_invalidas > 0:
                        st.error(f"❌ {coord_invalidas} coordenada(s) com formato inválido")
                        erros_criticos.append(f"Damages ({f_dam.name}): {coord_invalidas} coordenada(s) inválida(s)")
                    else:
                        st.success("✅ Coordenadas OK")
                if 'Type' in df_chk_m.columns:
                    tipos_sem_mapa = [
                        t for t in df_chk_m['Type'].dropna().unique()
                        if t.lower() not in MAPPING
                    ]
                    if tipos_sem_mapa:
                        st.warning(f"⚠️ Tipo(s) sem mapeamento SkySpecs: {', '.join(tipos_sem_mapa)}")
                        avisos.append(f"Damages ({f_dam.name}): tipo(s) sem mapeamento — {', '.join(tipos_sem_mapa)}")
                    else:
                        st.success("✅ Todos os tipos mapeados para SkySpecs")

    # --------------------------------------------------------------------------
    # 🔴 Casos Críticos — Severidade 5
    # --------------------------------------------------------------------------
    if f_dam_list:
        with st.expander("🔴 Casos Críticos — Severidade 5", expanded=True):
            criticos_all = []
            for f_dam in f_dam_list:
                f_dam.seek(0)
                df_raw = load_csv_robust(f_dam, is_damage=True)
                if df_raw is not None and "Type" in df_raw.columns:
                    # Exclui checkpoints usando o mesmo critério do convert_damages_df
                    is_cp = df_raw["Type"].str.strip().str.lower().apply(
                        lambda t: MAPPING.get(t, {}).get("_is_checkpoint", False)
                    )
                    df_real = df_raw[~is_cp].reset_index(drop=True)

                    if not df_real.empty:
                        f_dam.seek(0)
                        df_conv, _ = convert_damages_df(df_raw, f_dam.name)
                        df_conv = df_conv.reset_index(drop=True)

                        sev5_mask = df_conv["Severity"].astype(str) == "5"
                        if sev5_mask.any():
                            df5_raw = df_real[sev5_mask].reset_index(drop=True)
                            df5_conv = df_conv[sev5_mask].reset_index(drop=True)
                            for i in range(len(df5_conv)):
                                criticos_all.append({
                                    "Arquivo": f_dam.name,
                                    "Photo File Name": df5_conv.at[i, "Photo File Name"],
                                    "Tipo (Arthwind)": df5_raw.at[i, "Type"],
                                    "Sev antes": df5_raw.at[i, "Severity"] if "Severity" in df5_raw.columns else "",
                                    "Component": df5_conv.at[i, "Component"],
                                    "Material": df5_conv.at[i, "Material"],
                                    "Type (SkySpecs)": df5_conv.at[i, "Type"],
                                    "Subtype": df5_conv.at[i, "Subtype"],
                                    "Sev depois": df5_conv.at[i, "Severity"],
                                })

            if criticos_all:
                df_criticos = pd.DataFrame(criticos_all)
                st.markdown(f"**{len(criticos_all)} registro(s) com Severidade 5 após conversão:**")
                st.dataframe(
                    df_criticos,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Arquivo": st.column_config.TextColumn("Arquivo", width="medium"),
                        "Tipo (Arthwind)": st.column_config.TextColumn("Tipo (Arthwind)", width="medium"),
                        "Sev antes": st.column_config.TextColumn("Sev antes", width="small"),
                        "Sev depois": st.column_config.TextColumn("Sev depois", width="small"),
                    }
                )
            else:
                st.info("Nenhum registro com Severidade 5 nos arquivos carregados.")

    st.divider()
    if erros_criticos:
        st.error(f"🚫 Pacote bloqueado — {len(erros_criticos)} erro(s) crítico(s). Corrija antes de gerar.")
        for e in erros_criticos:
            st.markdown(f"- {e}")
    else:
        if avisos:
            for a in avisos:
                st.warning(f"⚠️ {a}")
        st.success("✅ Todos os arquivos atendem os requisitos da Horizon. Pacote liberado para geração.")
    st.markdown('</div>', unsafe_allow_html=True)


# ==============================================================================
# EXPORTAÇÃO
# ==============================================================================

if s_ok and d_ok and m_ok and pode_forjar and not erros_criticos:
    if st.button("GERAR PACOTE FINAL"):
        zip_buffer = io.BytesIO()
        erros_pos = []
        all_flags = []

        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zip_file:
            q = '"'
            removidas_set = set(st.session_state.turbinas_removidas)
            nomes_horizon = set(st.session_state.task_map.keys())
            nomes_atw_vinculados = set(st.session_state.vinculos_confirmados.values())
            valid_set = (nomes_horizon | nomes_atw_vinculados) - removidas_set

            # --- 1. Summary Final ---
            df_hor = load_horizon_base(f_horizon)
            df_atw = df_atw_dedup.copy()
            df_summary_final = None
            if df_hor is not None and df_atw is not None:
                hor_removidas_exp = set(st.session_state.turbinas_horizon_removidas)
                valid_set_hor = nomes_horizon - removidas_set - hor_removidas_exp
                df_hor = df_hor[df_hor['Turbine'].isin(valid_set_hor)].copy()
                date_col_atw = next((c for c in df_atw.columns if 'date' in c.lower() or 'data' in c.lower()), None)
                type_col_atw = next((c for c in df_atw.columns if 'inspection type' in c.lower()), None)
                atw_lookup = df_atw.drop_duplicates('Turbine').set_index('Turbine')
                vinculos_hor_to_atw = st.session_state.vinculos_confirmados
                def resolve_atw_name(t_hor):
                    return vinculos_hor_to_atw.get(t_hor, t_hor)
                if date_col_atw:
                    df_hor['Inspection Date'] = df_hor['Turbine'].map(
                        lambda t: atw_lookup.loc[resolve_atw_name(t), date_col_atw]
                        if resolve_atw_name(t) in atw_lookup.index else ''
                    )
                    df_hor['Inspection Date'] = pd.to_datetime(
                        df_hor['Inspection Date'], dayfirst=True, errors='coerce'
                    ).dt.strftime('%m/%d/%Y')
                if type_col_atw:
                    df_hor['Inspection Type'] = df_hor['Turbine'].map(
                        lambda t: atw_lookup.loc[resolve_atw_name(t), type_col_atw]
                        if resolve_atw_name(t) in atw_lookup.index else ''
                    )
                df_summary_final = df_hor
                zip_file.writestr("summary_final.csv", df_hor.to_csv(index=False))

            # --- 2. Details Filtrado ---
            df_d = load_csv_robust(f_det)
            df_details_final = None
            valid_photos = set()
            if df_d is not None:
                idc = 'ID' if 'ID' in df_d.columns else df_d.columns[0]
                atw_para_hor = {v: k for k, v in st.session_state.vinculos_confirmados.items()}
                nomes_atw_vinculados2 = set(st.session_state.vinculos_confirmados.values())
                valid_set_det = valid_set | nomes_atw_vinculados2
                df_d = df_d[df_d[idc].isin(valid_set_det)].copy()
                df_d[idc] = df_d[idc].map(lambda x: atw_para_hor.get(x, x))
                path_col = next(
                    (c for c in df_d.columns if c.lower() == 'path'),
                    next((c for c in df_d.columns if any(x in c.lower() for x in ['file', 'image']) and 'url' not in c.lower()),
                    next((c for c in df_d.columns if 'url' in c.lower()), df_d.columns[-1]))
                )
                valid_photos = {clean_filename(n) for n in df_d[path_col].unique() if n}
                df_d['Horizon Task ID'] = df_d[idc].map(lambda x: st.session_state.task_map.get(x, {}).get('Horizon Task ID'))
                df_details_final = df_d
                zip_file.writestr("details_final.csv", df_d.to_csv(index=False, sep=';'))

            # --- 3. Damages: filtrar + CONVERTER para SkySpecs ---
            damages_finais = []
            for f_dam in f_dam_list:
                df_m = load_csv_robust(f_dam, is_damage=True)
                if df_m is not None:
                    # Filtra por fotos que existem no Details
                    df_m = df_m[df_m['Photo File Name'].apply(clean_filename).isin(valid_photos)]
                    if not df_m.empty:
                        # Aplica conversão Arthwind → SkySpecs
                        df_converted, file_flags = convert_damages_df(df_m, f_dam.name)
                        all_flags.extend(file_flags)

                        if not df_converted.empty:
                            damages_finais.append((f_dam.name, df_converted))
                            # Escreve CSV com colunas SkySpecs
                            csv_lines = [",".join(SKYSPECS_COLUMNS)]
                            for _, row in df_converted.iterrows():
                                vals = []
                                for c in SKYSPECS_COLUMNS:
                                    v = str(row[c]).strip(q)
                                    vals.append(f"{q}{v}{q}" if c == 'Coordinates' else v)
                                csv_lines.append(",".join(vals))
                            zip_file.writestr(f_dam.name, "\n".join(csv_lines))

            # --- Relatório de FLAGS (se houver) ---
            if all_flags:
                df_flags = pd.DataFrame(all_flags)
                zip_file.writestr("ALERTAS_CONVERSAO.csv", df_flags.to_csv(index=False))

        # ==============================================================================
        # VERIFICAÇÃO PÓS-PROCESSAMENTO
        # ==============================================================================

        st.markdown('<div class="report-block">', unsafe_allow_html=True)
        st.subheader("5. VERIFICAÇÃO FINAL DO PACOTE")

        with st.expander("📄 Summary final", expanded=True):
            if df_summary_final is not None:
                for campo, label in [('Horizon Task ID', 'Horizon Task ID'), ('Inspection Date', 'Inspection Date'), ('Inspection Type', 'Inspection Type')]:
                    if campo in df_summary_final.columns:
                        sem_valor = df_summary_final[
                            df_summary_final[campo].isna() |
                            (df_summary_final[campo].astype(str).str.strip() == '') |
                            (df_summary_final[campo].astype(str).str.strip() == 'NaT')
                        ]
                        if not sem_valor.empty:
                            turbinas_prob = ', '.join(sorted(sem_valor['Turbine'].astype(str).unique()))
                            st.error(f"❌ {label} vazio em: {turbinas_prob}")
                            erros_pos.append(f"Summary: {label} vazio em {len(sem_valor)} turbina(s)")
                        else:
                            st.success(f"✅ {label} OK")
                    else:
                        st.error(f"❌ Coluna '{campo}' não encontrada no Summary final")
                        erros_pos.append(f"Summary: coluna '{campo}' ausente")

        with st.expander("📄 Details final", expanded=True):
            if df_details_final is not None:
                idc_det = 'ID' if 'ID' in df_details_final.columns else df_details_final.columns[0]
                dc1, dc2 = st.columns(2)
                dc1.metric("Turbinas no Details", df_details_final[idc_det].nunique())
                dc2.metric("Fotos no Details", len(df_details_final))
                st.divider()
                if 'Horizon Task ID' in df_details_final.columns:
                    sem_task = df_details_final[
                        df_details_final['Horizon Task ID'].isna() |
                        (df_details_final['Horizon Task ID'].astype(str).str.strip() == '')
                    ]
                    if not sem_task.empty:
                        turbinas_prob = ', '.join(sorted(sem_task[idc_det].astype(str).unique()))
                        st.error(f"❌ Horizon Task ID vazio em: {turbinas_prob}")
                        erros_pos.append(f"Details: Horizon Task ID vazio em {len(sem_task)} linha(s)")
                    else:
                        st.success("✅ Horizon Task ID OK")

        with st.expander("📄 Damages convertidos (SkySpecs)", expanded=True):
            total_arq = len(f_dam_list)
            total_proc = len(damages_finais)
            total_danos = sum(len(df_d) for _, df_d in damages_finais)
            total_flags = len(all_flags)

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Arquivos submetidos", total_arq)
            mc2.metric("Arquivos convertidos", total_proc)
            mc3.metric("Registros de dano", total_danos)
            mc4.metric("Alertas de conversão", total_flags,
                       delta_color="inverse" if total_flags > 0 else "normal")
            st.divider()

            if damages_finais:
                path_col_det = next(
                    (c for c in df_details_final.columns if any(x in c.lower() for x in ['path', 'file', 'image'])), None
                ) if df_details_final is not None else None
                fotos_details = {clean_filename(n) for n in df_details_final[path_col_det].unique() if n} if path_col_det else set()

                for nome_dam, df_dam in damages_finais:
                    n_rows = len(df_dam)
                    n_flags = sum(1 for f in all_flags if f["Arquivo"] == nome_dam)
                    st.markdown(f"**{nome_dam}** — {n_rows} registro(s)" + (f" | ⚠️ {n_flags} alerta(s)" if n_flags else " | ✅ sem alertas"))
                    if 'Photo File Name' in df_dam.columns:
                        fotos_dam = {clean_filename(n) for n in df_dam['Photo File Name'].unique() if n}
                        fotos_sem_match = fotos_dam - fotos_details
                        if fotos_sem_match:
                            st.error(f"❌ {len(fotos_sem_match)} foto(s) sem correspondência no Details")
                            erros_pos.append(f"Damages ({nome_dam}): {len(fotos_sem_match)} foto(s) sem correspondência")
                    # Verifica se colunas SkySpecs obrigatórias estão presentes
                    for col_req in ["Component", "Material", "Type", "Damage Location"]:
                        if col_req in df_dam.columns:
                            vazios_req = (df_dam[col_req].astype(str).str.strip() == '').sum()
                            if vazios_req > 0:
                                st.warning(f"⚠️ {vazios_req} linha(s) com '{col_req}' vazio")

                nomes_proc = {nome for nome, _ in damages_finais}
                descartados = [f.name for f in f_dam_list if f.name not in nomes_proc]
                if descartados:
                    st.warning(f"⚠️ {len(descartados)} arquivo(s) descartado(s) por não ter fotos no Details: {', '.join(descartados)}")

            if all_flags:
                with st.expander(f"⚠️ {len(all_flags)} alerta(s) de conversão — incluídos em ALERTAS_CONVERSAO.csv no ZIP"):
                    st.dataframe(pd.DataFrame(all_flags), use_container_width=True)

        st.divider()
        if erros_pos:
            st.error(f"🚫 Pacote gerado com {len(erros_pos)} problema(s). Corrija e gere novamente.")
            for e in erros_pos:
                st.markdown(f"- {e}")
        else:
            st.success("✅ Pacote verificado e aprovado. Pronto para download.")
            st.download_button(
                "⬇️ BAIXAR PACOTE (.ZIP)",
                data=zip_buffer.getvalue(),
                file_name="horizon_package.zip"
            )
        st.markdown('</div>', unsafe_allow_html=True)
