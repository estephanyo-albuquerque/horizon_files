import streamlit as st
import pandas as pd
import zipfile
import io
import os

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
        
        if not faltantes:
            st.success("Dados completos para as turbinas solicitadas pela Horizon.")
            pode_forjar = True
        else:
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
    st.markdown('</div>', unsafe_allow_html=True)

# --- EXPORTAÇÃO COM FILTRAGEM ---
if s_ok and d_ok and m_ok and pode_forjar:
    if st.button("GERAR PACOTE FINAL"):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zip_file:
            q = '"'
            # Conjunto de turbinas autorizadas pela Horizon
            valid_set = set(st.session_state.task_map.keys())
            
            # 1. Summary (Filtrado)
            df_s = load_csv_robust(f_sum)
            if df_s is not None:
                df_s = df_s[df_s['Turbine'].isin(valid_set)] # Filtro Mestre
                df_s['Horizon Task ID'] = df_s['Turbine'].map(lambda x: st.session_state.task_map.get(x, {}).get('Horizon Task ID'))
                df_s['Site'] = df_s['Turbine'].map(lambda x: st.session_state.task_map.get(x, {}).get('Site'))
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