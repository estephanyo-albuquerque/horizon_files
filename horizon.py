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
    f_horizon = st.file_uploader("Base Horizon", type=['csv'])
    h_ok = check_status(f_horizon, "HORIZON")
    if f_horizon:
        try:
            df_ref = pd.read_csv(f_horizon, sep=None, engine='python')
            if 'Turbine' in df_ref.columns:
                st.session_state.task_map = df_ref.drop_duplicates('Turbine').set_index('Turbine')[['Horizon Task ID', 'Site']].to_dict('index')
        except: pass
    st.markdown('</div>', unsafe_allow_html=True)

with c2:
    st.markdown('<div class="report-block">', unsafe_allow_html=True)
    st.subheader("2. DADOS INSPEÇÃO")
    f_sum = st.file_uploader("Summary", type=['csv'])
    s_ok = check_status(f_sum, "SUMMARY")
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
        turbinas_arthwind = set(df_s_val['Turbine'].unique())
        turbinas_horizon = set(st.session_state.task_map.keys())
        faltantes = turbinas_horizon - turbinas_arthwind
        extras = turbinas_arthwind - turbinas_horizon

        # --- CASO 1: turbinas extras no Arthwind ---
        if extras:
            st.warning(f"⚠️ {len(extras)} turbina(s) no Summary não existem na base Horizon: {', '.join(sorted(extras))}")
            remover = st.multiselect(
                "Selecione as turbinas EXTRAS que devem ser REMOVIDAS do pacote:",
                options=sorted(list(extras)),
                default=sorted(list(extras)),
                key="extras_remover"
            )
            if st.button("CONFIRMAR REMOÇÃO"):
                st.session_state['turbinas_removidas'] = remover
                st.rerun()

            removidas = st.session_state.get('turbinas_removidas', None)
            if removidas is not None:
                turbinas_arthwind -= set(removidas)
                if extras - set(removidas):
                    st.error("❌ Ainda há turbinas extras não removidas. O pacote não pode ser gerado.")
                else:
                    st.success(f"✅ {len(removidas)} turbina(s) extra(s) removida(s) do pacote.")

        # --- CASO 2: turbinas faltando no Arthwind ---
        if faltantes:
            st.warning(f"Atenção: Faltam {len(faltantes)} turbinas da base Horizon nos dados.")
            correcoes = {}
            cv1, cv2 = st.columns(2)
            for i, th in enumerate(sorted(list(faltantes))):
                with cv1 if i % 2 == 0 else cv2:
                    sel = st.selectbox(f"Vincular '{th}' (Horizon) a:", options=sorted(list(turbinas_arthwind)), key=f"v_{th}")
                    correcoes[th] = sel
            if st.button("CONFIRMAR VÍNCULOS"):
                for th, ta in correcoes.items():
                    st.session_state.task_map[ta] = st.session_state.task_map[th]
                st.rerun()

        # --- TUDO OK ---
        if not faltantes and not extras:
            st.success("✅ Dados completos para as turbinas solicitadas pela Horizon.")
            pode_forjar = True
        elif not faltantes and st.session_state.get('turbinas_removidas') is not None:
            if not (extras - set(st.session_state.get('turbinas_removidas', []))):
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
            removidas_set = set(st.session_state.get('turbinas_removidas', []))
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
                    st.warning(f"⚠️ Datas em formato BR (dd/mm/yyyy) — serão convertidas automaticamente para mm/dd/yyyy")
                    avisos.append("Summary: datas em formato BR serão convertidas")
                elif ambiguo:
                    st.warning(f"⚠️ Datas com formato ambíguo — verifique se estão em mm/dd/yyyy")
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

            # Horizon Task ID vazio
            if 'Horizon Task ID' in df_chk_s.columns:
                vazios = df_chk_s['Horizon Task ID'].isna().sum() + (df_chk_s['Horizon Task ID'] == '').sum()
                if vazios > 0:
                    st.error(f"❌ {vazios} linha(s) sem Horizon Task ID")
                    erros_criticos.append(f"Summary: {vazios} linha(s) sem Horizon Task ID")
                else:
                    st.success("✅ Horizon Task ID preenchido")

            # Site vazio
            if 'Site' in df_chk_s.columns:
                vazios_site = df_chk_s['Site'].isna().sum() + (df_chk_s['Site'] == '').sum()
                if vazios_site > 0:
                    st.error(f"❌ {vazios_site} linha(s) sem Site")
                    erros_criticos.append(f"Summary: {vazios_site} linha(s) sem Site")
                else:
                    st.success("✅ Site preenchido")

    # ---- DETAILS ----
    with st.expander("📄 Details", expanded=True):
        df_chk_d = load_csv_robust(f_det)
        if df_chk_d is not None:
            idc = 'ID' if 'ID' in df_chk_d.columns else df_chk_d.columns[0]
            valid_set_chk = set(st.session_state.task_map.keys()) - set(st.session_state.get('turbinas_removidas', []))
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
            url_col = next((c for c in df_chk_d.columns if 'url' in c.lower()), None)

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
                nao_numerico = df_chk_d[pd.to_numeric(df_chk_d[rad_col], errors='coerce').isna() & df_chk_d[rad_col].notna() & (df_chk_d[rad_col] != '')].shape[0]
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

                # Photo File Name vazio
                if 'Photo File Name' in df_chk_m.columns:
                    vazios_foto = df_chk_m['Photo File Name'].isna().sum() + (df_chk_m['Photo File Name'] == '').sum()
                    if vazios_foto > 0:
                        st.error(f"❌ {vazios_foto} linha(s) sem Photo File Name")
                        erros_criticos.append(f"Damages ({f_dam.name}): {vazios_foto} linha(s) sem Photo File Name")
                    else:
                        st.success("✅ Photo File Name preenchido")

                # Coordinates formato válido
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
            # Conjunto de turbinas autorizadas pela Horizon (excluindo removidas)
            removidas_set = set(st.session_state.get('turbinas_removidas', []))
            valid_set = set(st.session_state.task_map.keys()) - removidas_set

            # 1. Summary (Filtrado)
            df_s = load_csv_robust(f_sum)
            if df_s is not None:
                df_s = df_s[df_s['Turbine'].isin(valid_set)] # Filtro Mestre
                df_s['Horizon Task ID'] = df_s['Turbine'].map(lambda x: st.session_state.task_map.get(x, {}).get('Horizon Task ID'))
                df_s['Site'] = df_s['Turbine'].map(lambda x: st.session_state.task_map.get(x, {}).get('Site'))

                # Conversão de data para mm/dd/yyyy
                date_col = next((c for c in df_s.columns if 'date' in c.lower() or 'data' in c.lower()), None)
                if date_col:
                    df_s[date_col] = pd.to_datetime(
                        df_s[date_col], dayfirst=True, errors='coerce'
                    ).dt.strftime('%m/%d/%Y')

                zip_file.writestr("summary_final.csv", df_s.to_csv(index=False))

            # 2. Details (Filtrado)
            df_d = load_csv_robust(f_det)
            valid_photos = set()
            if df_d is not None:
                idc = 'ID' if 'ID' in df_d.columns else df_d.columns[0]
                df_d = df_d[df_d[idc].isin(valid_set)] # Filtro Mestre
                
                # Identifica fotos das turbinas válidas para filtrar Damages
                path_col = next((c for c in df_d.columns if any(x in c.lower() for x in ['path', 'file', 'image'])), df_d.columns[-1])
                valid_photos = {clean_filename(n) for n in df_d[path_col].unique() if n}
                
                df_d['Horizon Task ID'] = df_d[idc].map(lambda x: st.session_state.task_map.get(x, {}).get('Horizon Task ID'))
                zip_file.writestr("details_final.csv", df_d.to_csv(index=False, sep=';'))

            # 3. Damages (Filtrado por Vínculo de Imagem)
            for f_dam in f_dam_list:
                df_m = load_csv_robust(f_dam, is_damage=True)
                if df_m is not None:
                    # Filtra danos: só entram os que pertencem às fotos das turbinas autorizadas
                    df_m = df_m[df_m['Photo File Name'].apply(clean_filename).isin(valid_photos)]
                    
                    if not df_m.empty:
                        csv_lines = [",".join(df_m.columns)]
                        for _, row in df_m.iterrows():
                            line_vals = [f"{q}{str(row[c]).strip(q)}{q}" if c == 'Coordinates' else str(row[c]).strip(q) for c in df_m.columns]
                            csv_lines.append(",".join(line_vals))
                        zip_file.writestr(f_dam.name, "\n".join(csv_lines))

        st.download_button("BAIXAR PACOTE (.ZIP)", data=zip_buffer.getvalue(), file_name="horizon_package.zip")
