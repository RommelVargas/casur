import streamlit as st
import pandas as pd
import google.generativeai as genai
from PIL import Image
import io
import json
import re
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(
    page_title="Indicadores",
    page_icon="📋",  # <--- AQUI PUSE EL EMOJI DE LISTA
    layout="wide"
)

try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except:
    api_key = ""

if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("models/gemini-2.5-flash", generation_config={"temperature": 0.1})

# --- FUNCIONES ---
def clean_json(text):
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match: return match.group(0)
    return text

def get_data_gemini(image):
    prompt = """
    Transcribe SOLO LOS NÚMEROS de esta tabla manuscrita (CASUR).
    COLUMNAS (Izquierda a Derecha):
    1. Hora
    2. Vapor (Totalizador)
    3. Vapor (Temp)
    4. Vapor (Presión)
    5. Agua (Totalizador)
    6. Agua (Temp)
    7. Agua (Presión)
    8. Ingreso Bagacera (Totalizador)
    9. Retorno Bagacera (Totalizador)
    
    INSTRUCCIONES:
    - Devuelve JSON Array de arrays.
    - Ejemplo: [[ "07:00", 98000, 530, 85, 10000, 120, 110, 370000, 660000 ], ...]
    - Usa 0 si no se lee.
    """
    try:
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"Error: {e}"

def calcular_metricas(df, ini_vap, ini_agua, ini_ing, ini_ret):
    """Recálculo reactivo automático."""
    num_cols = ["Totalizador de Vapor", "Totalizador agua alimentación", 
                "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"]
    
    for c in num_cols:
        if c in df.columns: 
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    if "Totalizador de Vapor" in df.columns:
        df["Tons. Vapor"] = df["Totalizador de Vapor"].diff()
        if len(df) > 0: df.loc[0, "Tons. Vapor"] = df.loc[0, "Totalizador de Vapor"] - ini_vap

    if "Totalizador agua alimentación" in df.columns:
        df["Tons. Agua"] = df["Totalizador agua alimentación"].diff()
        if len(df) > 0: df.loc[0, "Tons. Agua"] = df.loc[0, "Totalizador agua alimentación"] - ini_agua

    if "Totalizador de báscula ingreso" in df.columns:
        df["Tons. Biomasa Alim."] = df["Totalizador de báscula ingreso"].diff()
        if len(df) > 0: df.loc[0, "Tons. Biomasa Alim."] = df.loc[0, "Totalizador de báscula ingreso"] - ini_ing

    if "Totalizador de báscula de retorno" in df.columns:
        df["Tons. Biomasa Ret."] = df["Totalizador de báscula de retorno"].diff()
        if len(df) > 0: df.loc[0, "Tons. Biomasa Ret."] = df.loc[0, "Totalizador de báscula de retorno"] - ini_ret
        
    return df

# --- INTERFAZ ---
st.title("Digitalizador Automático")

if not api_key:
    st.error("⚠️ Falta API Key")
    st.stop()

# --- BARRA LATERAL (INPUTS) ---
with st.sidebar:
    st.header("1. Configuración")
    fecha_dt = st.date_input("Fecha del Reporte", datetime.now())
    fecha_str = fecha_dt.strftime("%d%m%Y")
    
    st.header("2. Lecturas Iniciales (Ayer)")
    ini_vapor = st.number_input("Vapor Inicial", value=0.0)
    ini_agua = st.number_input("Agua Inicial", value=0.0)
    ini_ingreso = st.number_input("Ingreso Inicial", value=0.0)
    ini_retorno = st.number_input("Retorno Inicial", value=0.0)
    
    st.divider()
    archivo = st.file_uploader("Subir Foto", type=["jpg","png","jpeg"])
    
    if st.button("Restablecer todo"):
        if 'df_final' in st.session_state: del st.session_state['df_final']
        st.rerun()

# --- PROCESAMIENTO INICIAL ---
if archivo:
    # 1. Abrir y Corregir Orientación (Siempre Horizontal)
    img = Image.open(archivo)
    width, height = img.size
    
    # Si la foto está vertical (Alto > Ancho), la rotamos 90 grados (Positivo = Antihorario)
    if height > width:
        img = img.rotate(90, expand=True) # <--- CAMBIO AQUI (Era -90)

    # 2. Mostrar la foto SOLO si el usuario quiere (Expander)
    with st.expander("Ver Foto Original (Click para abrir)", expanded=False):
        st.image(img, use_column_width=True, caption="Imagen Rotada Automáticamente")

    # 3. Botón de Procesar
    if 'df_final' not in st.session_state:
        if st.button("PROCESAR IMAGEN", type="primary"):
            with st.spinner("Analizando..."):
                resp = get_data_gemini(img)
                try:
                    data = json.loads(clean_json(resp))
                    cols = ["HORA", "Totalizador de Vapor", "Temperatura de vapor", "Presión de Vapor",
                            "Totalizador agua alimentación", "Temperatura agua alimentación", "Presión agua de alimentación",
                            "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"]
                    
                    df = pd.DataFrame(data)
                    df = df.iloc[:, :9] 
                    df.columns = cols[:len(df.columns)]
                    df.insert(0, "FECHA", fecha_dt)
                    
                    df = calcular_metricas(df, ini_vapor, ini_agua, ini_ingreso, ini_retorno)
                    st.session_state['df_final'] = df
                    st.rerun()
                except:
                    st.error("No se pudo leer la tabla. Intenta otra foto.")

# --- EDICIÓN Y RESULTADOS ---
if 'df_final' in st.session_state:
    st.divider()
    st.subheader("Tabla de Datos (Editable)")
    st.caption("Si editas un número (columnas blancas), presiona ENTER y el cálculo (gris) se actualiza solo.")

    columnas_bloqueadas = ["Tons. Vapor", "Tons. Agua", "Tons. Biomasa Alim.", "Tons. Biomasa Ret.", "FECHA"]

    df_editado = st.data_editor(
        st.session_state['df_final'],
        disabled=columnas_bloqueadas,
        num_rows="dynamic",
        key="editor_datos",
        use_container_width=True,
        height=500
    )

    inputs_cols = [c for c in df_editado.columns if c not in columnas_bloqueadas]
    
    if not df_editado[inputs_cols].equals(st.session_state['df_final'][inputs_cols]):
        df_recalculado = calcular_metricas(df_editado, ini_vapor, ini_agua, ini_ingreso, ini_retorno)
        st.session_state['df_final'] = df_recalculado
        st.rerun()

    st.write("---")
    col1, col2 = st.columns([1,1])
    with col1:
        nombre_archivo = st.text_input("Nombre del Archivo:", value=f"Indicadores de egersa {fecha_str}.xlsx")
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df_editado.to_excel(writer, index=False, sheet_name="Bitacora")
            workbook = writer.book
            worksheet = writer.sheets['Bitacora']
            fmt1 = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
            fmt2 = workbook.add_format({'num_format': 'dd/mm/yyyy', 'border': 1})
            
            for i, col in enumerate(df_editado.columns):
                worksheet.write(0, i, col, fmt1)
                if col == "FECHA": worksheet.set_column(i, i, 12, fmt2)
                else: worksheet.set_column(i, i, 15)

        st.download_button(
            label="📥 DESCARGAR EXCEL FINAL",
            data=buffer.getvalue(),
            file_name=nombre_archivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )