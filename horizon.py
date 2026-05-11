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

# --- FUNÇÕES ---

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
    """
    Retorna a turbina ATW mais similar ao nome Horizon.
    Usa SequenceMatcher para comparar strings normalizadas.
    """
    def normalizar(s):
        # Remove espaços, hifens, zeros à esquerda e lowercase
        s = s.lower()
        s = re.sub(r'[-_\s]', '', s)          # remove separadores
        s = re.sub(r'0+(\d)', r'\1', s)        # remove zeros à esquerda
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
    """Remove duplicatas do ATW mantendo a primeira ocorrência por Turbine."""
    if df is None or 'Turbine' not in df.columns:
        return df, 0
    total_antes = len(df)
    df_dedup = df.drop_duplicates(subset='Turbine', keep='first').reset_index(drop=True)
    duplicatas_removidas = total_antes - len(df_dedup)
    return df_dedup, duplicatas_removidas

# --- SIDEBAR ---
st.sidebar.header("STATUS DOS ARQUIVOS")

def check_status(file, name):
    if file:
        st.sidebar.markdown(f'<div class="status-container status-on">✓ {name}</div>', unsafe_allow_html=True)
        return True
    st.sidebar.markdown(f'<div class="status-container status-off">✗ {name}</div>', unsafe_allow_html=True)
    return False

# --- INPUTS ---
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
                # Reaplicar vínculos confirmados após qualquer rerun
                # Sem isso, as chaves ATW somem do task_map e os damages TAC ficam de fora
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
                f"⚠️ O Summary ATW continha **{n_duplicatas} linha(s) duplicada(s)** "
                f"(mesma Turbine repetida). Foram removidas automaticamente, mantendo a primeira ocorrência de cada turbina."
            )

# --- VALIDAÇÃO ---
pode_forjar = False

if h_ok and s_ok and df_atw_dedup is not None:
    st.markdown('<div class="report-block">', unsafe_allow_html=True)
    st.subheader("3. VALIDAÇÃO DE NOMENCLATURA")

    turbinas_atw = sorted([
        t for t in df_atw_dedup['Turbine'].unique()
        if t and str(t).strip() != ''
    ])
    turbinas_hor = sorted([
        t for t in st.session_state.task_map.keys()
        if t and str(t).strip() != ''
    ])

    set_atw = set(turbinas_atw)
    set_hor = set(turbinas_hor)

    # Aplica vínculos já confirmados: adiciona turbinas ATW mapeadas ao set_hor efetivo
    vinculos = st.session_state.vinculos_confirmados  # {turbina_hor: turbina_atw}
    set_hor_mapeado = set(vinculos.values())  # ATW já vinculadas
    set_hor_sem_vinculo = set_hor - set(vinculos.keys())  # Horizon ainda sem vínculo

    extras    = sorted(set_atw - set_hor - set_hor_mapeado)   # no ATW mas não na Horizon e não vinculadas
    faltantes = sorted(set_hor_sem_vinculo - set_atw)          # na Horizon mas não no ATW e sem vínculo

    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Turbinas na Horizon", len(turbinas_hor))
    cc2.metric("Turbinas no Summary ATW", len(turbinas_atw))
    delta = len(turbinas_atw) - len(turbinas_hor)
    cc3.metric("Diferença (ATW − Horizon)", delta, delta_color="inverse")

    st.divider()

    # --- CASO 1: turbinas extras no ATW ---
    removidas = st.session_state.turbinas_removidas

    if extras:
        st.warning(
            f"⚠️ {len(extras)} turbina(s) presente(s) no ATW mas **ausente(s) na Horizon**: "
            f"{', '.join(extras)}"
        )
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
            st.error(
                f"❌ Ainda há {len(ainda_extras)} turbina(s) extra(s) sem resolução: "
                f"{', '.join(ainda_extras)}"
            )
        else:
            if removidas:
                st.success(f"✅ {len([e for e in removidas if e in extras])} turbina(s) extra(s) removida(s) do pacote.")

    # --- CASO 2: turbinas faltando no ATW ---
    if faltantes:
        st.warning(
            f"⚠️ {len(faltantes)} turbina(s) da Horizon **ausente(s) no ATW**: "
            f"{', '.join(faltantes)}"
        )

        # Opções disponíveis: turbinas ATW que não foram removidas e não estão já vinculadas
        removidas_set = set(st.session_state.turbinas_removidas)
        ja_vinculadas = set(vinculos.values())
        opcoes_atw = sorted(set_atw - removidas_set - ja_vinculadas)

        if opcoes_atw:
            correcoes = {}
            cv1, cv2 = st.columns(2)
            for i, th in enumerate(faltantes):
                with cv1 if i % 2 == 0 else cv2:
                    # Sugestão automática por similaridade de string
                    sugerido, score = sugerir_match(th, opcoes_atw)
                    default_idx = opcoes_atw.index(sugerido) if sugerido in opcoes_atw else 0
                    label_score = f" ({score:.0%} similar)" if score < 1.0 else " (idêntico)"
                    sel = st.selectbox(
                        f"Vincular '{th}' (Horizon) a: — sugestão: **{sugerido}**{label_score}",
                        options=opcoes_atw,
                        index=default_idx,
                        key=f"v_{th}"
                    )
                    correcoes[th] = sel

            if st.button("CONFIRMAR VÍNCULOS"):
                # Atualiza task_map: turbina ATW herda dados da turbina Horizon
                for th, ta in correcoes.items():
                    if th in st.session_state.task_map:
                        st.session_state.task_map[ta] = st.session_state.task_map[th]
                # Salva vínculos confirmados
                st.session_state.vinculos_confirmados.update(correcoes)
                st.rerun()

        else:
            st.error("❌ Não há turbinas disponíveis no ATW para vincular.")

    # Exibe vínculos já confirmados
    if vinculos:
        with st.expander(f"🔗 {len(vinculos)} vínculo(s) confirmado(s)", expanded=False):
            for th, ta in vinculos.items():
                st.markdown(f"- **{th}** (Horizon) → **{ta}** (ATW)")

    # --- TUDO OK ---
    removidas_final = st.session_state.turbinas_removidas
    ainda_extras_final = [
        e for e in (set_atw - set_hor - set(vinculos.values()))
        if e not in removidas_final
    ]
    faltantes_final = sorted(set_hor - set(vinculos.keys()) - set_atw)

    if not faltantes_final and not ainda_extras_final:
        st.success("✅ Dados completos para as turbinas solicitadas pela Horizon.")
        pode_forjar = True

    st.markdown('</div>', unsafe_allow_html=True)

# --- VERIFICADOR DE REQUISITOS HORIZON ---
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

    # ---- SUMMARY ----
    with st.expander("📄 Summary", expanded=True):
        # Usa df já deduplicado
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
                formato_br = sample.apply(
                    lambda x: bool(re.match(r'^\d{2}/\d{2}/\d{4}$', str(x))) and int(str(x).split('/')[0]) > 12
                ).any()
                ambiguo = sample.apply(
                    lambda x: bool(re.match(r'^\d{2}/\d{2}/\d{4}$', str(x))) and int(str(x).split('/')[0]) <= 12
                ).any()
                if formato_br:
                    st.warning("⚠️ Datas em formato BR (dd/mm/yyyy) — serão convertidas automaticamente para mm/dd/yyyy")
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

    # ---- DETAILS ----
    with st.expander("📄 Details", expanded=True):
        df_chk_d = load_csv_robust(f_det)
        if df_chk_d is not None:
            idc = 'ID' if 'ID' in df_chk_d.columns else df_chk_d.columns[0]
            # Inclui nomes ATW dos vínculos no valid_set de verificação
            nomes_atw_chk = set(st.session_state.vinculos_confirmados.values())
            valid_set_chk = (set(st.session_state.task_map.keys()) | nomes_atw_chk) - set(st.session_state.turbinas_removidas)
            df_chk_d = df_chk_d[df_chk_d[idc].isin(valid_set_chk)]

            # Prioriza 'Path' sobre 'Image URL' para evitar URLs completas no match
            path_col = next(
                (c for c in df_chk_d.columns if c.lower() == 'path'),
                next((c for c in df_chk_d.columns if any(x in c.lower() for x in ['file', 'image']) and 'url' not in c.lower()), None)
            )
            url_col  = next((c for c in df_chk_d.columns if 'url' in c.lower()), None)

            if path_col:
                vazios_path = df_chk_d[path_col].isna().sum() + (df_chk_d[path_col] == '').sum()
                if vazios_path > 0:
                    st.error(f"❌ {vazios_path} linha(s) sem Path ({path_col})")
                    erros_criticos.append(f"Details: {vazios_path} linha(s) sem Path")
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
                nao_numerico = df_chk_d[
                    pd.to_numeric(df_chk_d[rad_col], errors='coerce').isna() &
                    df_chk_d[rad_col].notna() &
                    (df_chk_d[rad_col] != '')
                ].shape[0]
                if nao_numerico > 0:
                    st.error(f"❌ {nao_numerico} valor(es) não numérico(s) em Radial Distance")
                    erros_criticos.append(f"Details: {nao_numerico} valor(es) não numérico(s) em Radial Distance")
                else:
                    st.success(f"✅ Radial Distance OK ({rad_col})")
            else:
                st.warning("⚠️ Coluna de Radial Distance não identificada")
                avisos.append("Details: coluna de Radial Distance não identificada")

    # ---- DAMAGES ----
    with st.expander("📄 Damages", expanded=True):
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

    # --- RESULTADO FINAL ---
    st.divider()
    if erros_criticos:
        st.error(f"🚫 Pacote bloqueado — {len(erros_criticos)} erro(s) crítico(s) encontrado(s). Corrija antes de gerar.")
        for e in erros_criticos:
            st.markdown(f"- {e}")
    else:
        if avisos:
            for a in avisos:
                st.warning(f"⚠️ {a}")
        st.success("✅ Todos os arquivos atendem os requisitos da Horizon. Pacote liberado para geração.")

    st.markdown('</div>', unsafe_allow_html=True)

# --- EXPORTAÇÃO ---
if s_ok and d_ok and m_ok and pode_forjar and not erros_criticos:
    if st.button("GERAR PACOTE FINAL"):
        zip_buffer = io.BytesIO()
        erros_pos = []

        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zip_file:
            q = '"'
            removidas_set = set(st.session_state.turbinas_removidas)

            # valid_set construído diretamente: nomes Horizon + nomes ATW dos vínculos
            # Não depende do task_map ter sido reaplicado corretamente no rerun
            nomes_horizon = set(st.session_state.task_map.keys())
            nomes_atw_vinculados = set(st.session_state.vinculos_confirmados.values())
            valid_set = (nomes_horizon | nomes_atw_vinculados) - removidas_set

            # 1. Summary Final
            df_hor = load_horizon_base(f_horizon)
            df_atw = df_atw_dedup.copy()  # já deduplicado
            df_summary_final = None
            if df_hor is not None and df_atw is not None:
                # Summary filtra apenas por nomes Horizon (não ATW), pois df_hor['Turbine'] usa nomenclatura Horizon
                valid_set_hor = nomes_horizon - removidas_set
                df_hor = df_hor[df_hor['Turbine'].isin(valid_set_hor)].copy()

                date_col_atw = next((c for c in df_atw.columns if 'date' in c.lower() or 'data' in c.lower()), None)
                type_col_atw = next((c for c in df_atw.columns if 'inspection type' in c.lower()), None)
                atw_lookup = df_atw.drop_duplicates('Turbine').set_index('Turbine')

                # Mapa Horizon → ATW: para turbinas vinculadas usa o nome ATW; demais usam o próprio nome
                vinculos_hor_to_atw = st.session_state.vinculos_confirmados  # {nome_hor: nome_atw}

                def resolve_atw_name(t_hor):
                    """Retorna o nome ATW correspondente a uma turbina Horizon."""
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

            # 2. Details (Filtrado)
            df_d = load_csv_robust(f_det)
            df_details_final = None
            valid_photos = set()
            if df_d is not None:
                idc = 'ID' if 'ID' in df_d.columns else df_d.columns[0]

                # Inverte vínculos: {nome_atw: nome_horizon}
                # Permite traduzir IDs ATW do Details para nomes Horizon antes do join
                atw_para_hor = {v: k for k, v in st.session_state.vinculos_confirmados.items()}

                # Filtra pelo valid_set expandido (nomes Horizon + nomes ATW vinculados)
                nomes_atw_vinculados = set(st.session_state.vinculos_confirmados.values())
                valid_set_det = valid_set | nomes_atw_vinculados
                df_d = df_d[df_d[idc].isin(valid_set_det)].copy()

                # Substitui IDs ATW vinculados pelo nome Horizon correspondente
                # Ex: TAC-II-01 → TACAICO II - 01, para que o join com task_map funcione
                df_d[idc] = df_d[idc].map(lambda x: atw_para_hor.get(x, x))

                # Prioriza 'Path' (basename limpo) sobre 'Image URL' (URL completa)
                path_col = next(
                    (c for c in df_d.columns if c.lower() == 'path'),
                    next((c for c in df_d.columns if any(x in c.lower() for x in ['file', 'image']) and 'url' not in c.lower()),
                    next((c for c in df_d.columns if 'url' in c.lower()), df_d.columns[-1]))
                )
                valid_photos = {clean_filename(n) for n in df_d[path_col].unique() if n}

                df_d['Horizon Task ID'] = df_d[idc].map(lambda x: st.session_state.task_map.get(x, {}).get('Horizon Task ID'))
                df_details_final = df_d
                zip_file.writestr("details_final.csv", df_d.to_csv(index=False, sep=';'))

            # 3. Damages (Filtrado)
            damages_finais = []
            for f_dam in f_dam_list:
                df_m = load_csv_robust(f_dam, is_damage=True)
                if df_m is not None:
                    df_m = df_m[df_m['Photo File Name'].apply(clean_filename).isin(valid_photos)]
                    if not df_m.empty:
                        damages_finais.append((f_dam.name, df_m))
                        csv_lines = [",".join(df_m.columns)]
                        for _, row in df_m.iterrows():
                            line_vals = [f"{q}{str(row[c]).strip(q)}{q}" if c == 'Coordinates' else str(row[c]).strip(q) for c in df_m.columns]
                            csv_lines.append(",".join(line_vals))
                        zip_file.writestr(f_dam.name, "\n".join(csv_lines))

        # --- VERIFICAÇÃO PÓS-PROCESSAMENTO ---
        st.markdown('<div class="report-block">', unsafe_allow_html=True)
        st.subheader("5. VERIFICAÇÃO FINAL DO PACOTE")

        with st.expander("📄 Summary final", expanded=True):
            if df_summary_final is not None:
                for campo, label in [('Horizon Task ID', 'Horizon Task ID'), ('Inspection Date', 'Inspection Date'), ('Inspection Type', 'Inspection Type')]:
                    if campo in df_summary_final.columns:
                        sem_valor = df_summary_final[
                            df_summary_final[campo].isna() | (df_summary_final[campo].astype(str).str.strip() == '') | (df_summary_final[campo].astype(str).str.strip() == 'NaT')
                        ]
                        if not sem_valor.empty:
                            turbinas_problema = ', '.join(sorted(sem_valor['Turbine'].astype(str).unique()))
                            st.error(f"❌ {label} vazio em: {turbinas_problema}")
                            erros_pos.append(f"Summary: {label} vazio em {len(sem_valor)} turbina(s)")
                        else:
                            st.success(f"✅ {label} OK")
                    else:
                        st.error(f"❌ Coluna '{campo}' não encontrada no Summary final")
                        erros_pos.append(f"Summary: coluna '{campo}' ausente")

        with st.expander("📄 Details final", expanded=True):
            if df_details_final is not None:
                if 'Horizon Task ID' in df_details_final.columns:
                    sem_task = df_details_final[
                        df_details_final['Horizon Task ID'].isna() | (df_details_final['Horizon Task ID'].astype(str).str.strip() == '')
                    ]
                    if not sem_task.empty:
                        turbinas_problema = ', '.join(sorted(sem_task[idc].astype(str).unique()))
                        st.error(f"❌ Horizon Task ID vazio após join em: {turbinas_problema}")
                        erros_pos.append(f"Details: Horizon Task ID vazio em {len(sem_task)} linha(s)")
                    else:
                        st.success("✅ Horizon Task ID OK")

                path_col_chk = next((c for c in df_details_final.columns if any(x in c.lower() for x in ['path', 'file', 'image'])), None)
                url_col_chk  = next((c for c in df_details_final.columns if 'url' in c.lower()), None)

                for col, label in [(path_col_chk, 'Path'), (url_col_chk, 'URL')]:
                    if col:
                        vazios = df_details_final[
                            df_details_final[col].isna() | (df_details_final[col].astype(str).str.strip() == '')
                        ].shape[0]
                        if vazios > 0:
                            st.error(f"❌ {label} vazio em {vazios} linha(s)")
                            erros_pos.append(f"Details: {label} vazio em {vazios} linha(s)")
                        else:
                            st.success(f"✅ {label} OK")

        with st.expander("📄 Damages final", expanded=True):
            if damages_finais:
                path_col_det = next((c for c in df_details_final.columns if any(x in c.lower() for x in ['path', 'file', 'image'])), None) if df_details_final is not None else None
                fotos_details = {clean_filename(n) for n in df_details_final[path_col_det].unique() if n} if path_col_det else set()

                for nome_dam, df_dam in damages_finais:
                    st.markdown(f"**{nome_dam}**")
                    if 'Photo File Name' in df_dam.columns:
                        fotos_dam = {clean_filename(n) for n in df_dam['Photo File Name'].unique() if n}
                        fotos_sem_match = fotos_dam - fotos_details
                        if fotos_sem_match:
                            st.error(f"❌ {len(fotos_sem_match)} foto(s) no Damage sem correspondência no Details: {', '.join(sorted(fotos_sem_match))}")
                            erros_pos.append(f"Damages ({nome_dam}): {len(fotos_sem_match)} foto(s) sem correspondência no Details")
                        else:
                            st.success("✅ Todas as fotos encontradas no Details")
            else:
                st.info("Nenhum arquivo de Damages gerado.")

        st.divider()
        if erros_pos:
            st.error(f"🚫 Pacote gerado com {len(erros_pos)} problema(s). Corrija e gere novamente.")
            for e in erros_pos:
                st.markdown(f"- {e}")
        else:
            st.success("✅ Pacote verificado e aprovado. Pronto para download.")
            st.download_button("⬇️ BAIXAR PACOTE (.ZIP)", data=zip_buffer.getvalue(), file_name="horizon_package.zip")

        st.markdown('</div>', unsafe_allow_html=True)
