import streamlit as st
import pandas as pd
import zipfile
import io
import os
import re

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
    """
    Carrega o summary_base da Horizon, pulando as linhas de cabeçalho
    de instrução (Explanation e Valid Data Options) antes dos dados reais.
    Retorna DataFrame limpo com apenas as linhas de dados.
    """
    if uploaded_file is None: return None
    try:
        content = uploaded_file.getvalue().decode('utf-8', errors='ignore')
        lines = [l for l in content.splitlines() if l.strip()]
        if not lines: return None

        # A primeira linha é sempre o cabeçalho real (Notes, ID, Description, ...)
        header_line = lines[0]
        sep = ';' if header_line.count(';') > header_line.count(',') else ','
        header = [h.strip().replace('"', '') for h in header_line.split(sep)]

        # Pula linhas de instrução: qualquer linha cujo primeiro campo
        # contenha "DELETE THIS ROW" ou "Explanation" ou "Valid Data"
        skip_keywords = ['delete this row', 'explanation:', 'valid data options']
        data = []
        for line in lines[1:]:
            first_field = line.split(sep)[0].strip().strip('"').lower()
            if any(kw in first_field for kw in skip_keywords):
                continue
            parts = line.split(sep)
            data.append([p.strip().strip('"') for p in parts[:len(header)]])

        df = pd.DataFrame(data, columns=header)

        # Remove coluna "Notes" se existir (é só metadado do template)
        if 'Notes' in df.columns:
            df = df.drop(columns=['Notes'])

        # Filtra linhas completamente vazias
        df = df[df.apply(lambda row: any(v.strip() != '' for v in row.astype(str)), axis=1)]

        return df
    except Exception as e:
        st.error(f"Erro ao carregar base Horizon: {e}")
        return None

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

# --- VALIDAÇÃO ---
pode_forjar = False

if h_ok and s_ok:
    st.markdown('<div class="report-block">', unsafe_allow_html=True)
    st.subheader("3. VALIDAÇÃO DE NOMENCLATURA")
    df_s_val = load_csv_robust(f_sum)
    if df_s_val is not None:

        # Listas limpas e ordenadas
        turbinas_atw = sorted([
            t for t in df_s_val['Turbine'].unique()
            if t and str(t).strip() != ''
        ])
        turbinas_hor = sorted([
            t for t in st.session_state.task_map.keys()
            if t and str(t).strip() != ''
        ])

        set_atw = set(turbinas_atw)
        set_hor = set(turbinas_hor)
        extras    = sorted(set_atw - set_hor)   # no ATW mas não na Horizon
        faltantes = sorted(set_hor - set_atw)   # na Horizon mas não no ATW

        # --- CONTADORES ---
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("Turbinas na Horizon", len(turbinas_hor))
        cc2.metric("Turbinas no Summary ATW", len(turbinas_atw))
        delta = len(turbinas_atw) - len(turbinas_hor)
        cc3.metric("Diferença (ATW − Horizon)", delta, delta_color="inverse")

        st.divider()

        # --- CASO 1: turbinas extras no ATW ---
        if extras:
            st.warning(
                f"⚠️ {len(extras)} turbina(s) presente(s) no ATW mas **ausente(s) na Horizon**: "
                f"{', '.join(extras)}"
            )
            remover = st.multiselect(
                "Selecione as turbinas EXTRAS para REMOVER do pacote:",
                options=extras,
                default=extras,
                key="extras_remover"
            )
            if st.button("CONFIRMAR REMOÇÃO"):
                st.session_state['turbinas_removidas'] = remover
                st.rerun()

            removidas = st.session_state.get('turbinas_removidas') or []
            ainda_extras = [e for e in extras if e not in removidas]
            if ainda_extras:
                st.error(
                    f"❌ Ainda há {len(ainda_extras)} turbina(s) extra(s) sem resolução: "
                    f"{', '.join(ainda_extras)}"
                )
            else:
                if removidas:
                    st.success(f"✅ {len(removidas)} turbina(s) extra(s) removida(s) do pacote.")

        # --- CASO 2: turbinas faltando no ATW ---
        if faltantes:
            st.warning(
                f"⚠️ {len(faltantes)} turbina(s) da Horizon **ausente(s) no ATW**: "
                f"{', '.join(faltantes)}"
            )
            removidas = st.session_state.get('turbinas_removidas') or []
            opcoes_atw = sorted(set_atw - set(removidas))
            if opcoes_atw:
                correcoes = {}
                cv1, cv2 = st.columns(2)
                for i, th in enumerate(faltantes):
                    with cv1 if i % 2 == 0 else cv2:
                        sel = st.selectbox(
                            f"Vincular '{th}' (Horizon) a:",
                            options=opcoes_atw,
                            key=f"v_{th}"
                        )
                        correcoes[th] = sel
                if st.button("CONFIRMAR VÍNCULOS"):
                    for th, ta in correcoes.items():
                        st.session_state.task_map[ta] = st.session_state.task_map[th]
                    st.rerun()
            else:
                st.error("❌ Não há turbinas disponíveis no ATW para vincular.")

        # --- TUDO OK ---
        removidas_final = st.session_state.get('turbinas_removidas') or []
        ainda_extras_final = [e for e in extras if e not in removidas_final]
        if not faltantes and not ainda_extras_final:
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
        df_chk_s = load_csv_robust(f_sum)
        if df_chk_s is not None:
            removidas_set = set(st.session_state.get('turbinas_removidas') or [])
            df_chk_s = df_chk_s[~df_chk_s['Turbine'].isin(removidas_set)]

            # Formato de data
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

            # Inspection Type
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
            valid_set_chk = set(st.session_state.task_map.keys()) - set(st.session_state.get('turbinas_removidas') or [])
            df_chk_d = df_chk_d[df_chk_d[idc].isin(valid_set_chk)]

            # Horizon Task ID vazio
            if 'Horizon Task ID' in df_chk_d.columns:
                vazios = df_chk_d['Horizon Task ID'].isna().sum() + (df_chk_d['Horizon Task ID'] == '').sum()
                if vazios > 0:
                    st.error(f"❌ {vazios} linha(s) sem Horizon Task ID")
                    erros_criticos.append(f"Details: {vazios} linha(s) sem Horizon Task ID")
                else:
                    st.success("✅ Horizon Task ID preenchido")

            # URL e Path
            path_col = next((c for c in df_chk_d.columns if any(x in c.lower() for x in ['path', 'file', 'image'])), None)
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

            # Radial Distance numérico
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
        coord_pattern = re.compile(r'^\[(\[\d+,\d+\],?)+\]$')
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

# --- EXPORTAÇÃO COM FILTRAGEM ---
if s_ok and d_ok and m_ok and pode_forjar and not erros_criticos:
    if st.button("GERAR PACOTE FINAL"):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zip_file:
            q = '"'
            removidas_set = set(st.session_state.get('turbinas_removidas') or [])
            valid_set = set(st.session_state.task_map.keys()) - removidas_set

            # 1. Summary Final — base Horizon + dados do ATW via join por Turbine
            df_hor = load_horizon_base(f_horizon)
            df_atw = load_csv_robust(f_sum)
            if df_hor is not None and df_atw is not None:
                # Filtra base Horizon pelas turbinas válidas
                df_hor = df_hor[df_hor['Turbine'].isin(valid_set)].copy()

                # Prepara lookup do ATW: Turbine → Inspection Date + Inspection Type
                date_col_atw = next((c for c in df_atw.columns if 'date' in c.lower() or 'data' in c.lower()), None)
                type_col_atw = next((c for c in df_atw.columns if 'inspection type' in c.lower()), None)

                atw_lookup = df_atw.drop_duplicates('Turbine').set_index('Turbine')

                # Injeta Inspection Date (com conversão para mm/dd/yyyy)
                if date_col_atw:
                    df_hor['Inspection Date'] = df_hor['Turbine'].map(
                        lambda t: atw_lookup.loc[t, date_col_atw]
                        if t in atw_lookup.index else ''
                    )
                    df_hor['Inspection Date'] = pd.to_datetime(
                        df_hor['Inspection Date'], dayfirst=True, errors='coerce'
                    ).dt.strftime('%m/%d/%Y')

                # Injeta Inspection Type
                if type_col_atw:
                    df_hor['Inspection Type'] = df_hor['Turbine'].map(
                        lambda t: atw_lookup.loc[t, type_col_atw]
                        if t in atw_lookup.index else ''
                    )

                zip_file.writestr("summary_final.csv", df_hor.to_csv(index=False))

            # 2. Details (Filtrado)
            df_d = load_csv_robust(f_det)
            valid_photos = set()
            if df_d is not None:
                idc = 'ID' if 'ID' in df_d.columns else df_d.columns[0]
                df_d = df_d[df_d[idc].isin(valid_set)]

                path_col = next((c for c in df_d.columns if any(x in c.lower() for x in ['path', 'file', 'image'])), df_d.columns[-1])
                valid_photos = {clean_filename(n) for n in df_d[path_col].unique() if n}

                df_d['Horizon Task ID'] = df_d[idc].map(lambda x: st.session_state.task_map.get(x, {}).get('Horizon Task ID'))
                zip_file.writestr("details_final.csv", df_d.to_csv(index=False, sep=';'))

            # 3. Damages (Filtrado por Vínculo de Imagem)
            for f_dam in f_dam_list:
                df_m = load_csv_robust(f_dam, is_damage=True)
                if df_m is not None:
                    df_m = df_m[df_m['Photo File Name'].apply(clean_filename).isin(valid_photos)]
                    if not df_m.empty:
                        csv_lines = [",".join(df_m.columns)]
                        for _, row in df_m.iterrows():
                            line_vals = [f"{q}{str(row[c]).strip(q)}{q}" if c == 'Coordinates' else str(row[c]).strip(q) for c in df_m.columns]
                            csv_lines.append(",".join(line_vals))
                        zip_file.writestr(f_dam.name, "\n".join(csv_lines))

        st.download_button("BAIXAR PACOTE (.ZIP)", data=zip_buffer.getvalue(), file_name="horizon_package.zip")
