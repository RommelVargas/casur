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
    page_icon="🏭",
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
    # 1. Convertir a números
    num_cols = ["Totalizador de Vapor", "Totalizador agua alimentación", 
                "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"]
    
    for c in num_cols:
        if c in df.columns: 
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    # 2. Calcular diferencias
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
st.title("Digitalizador de Indicadores")

if not api_key:
    st.error("⚠️ Falta API Key")
    st.stop()

# --- BARRA LATERAL ---
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

# --- PROCESAMIENTO ---
if archivo:
    img = Image.open(archivo)
    width, height = img.size
    
    # Rotación Automática (Positivo = Antihorario)
    if height > width:
        img = img.rotate(90, expand=True)

    with st.expander("Ver Foto Original", expanded=False):
        st.image(img, use_column_width=True, caption="Imagen Rotada")

    if 'df_final' not in st.session_state:
        if st.button("PROCESAR IMAGEN", type="primary"):
            with st.spinner("Generando tabla..."):
                resp = get_data_gemini(img)
                try:
                    data = json.loads(clean_json(resp))
                    # Nombres de columnas RAW (lo que lee la IA)
                    cols_raw = ["HORA", "Totalizador de Vapor", "Temperatura de vapor", "Presión de Vapor",
                                "Totalizador agua alimentación", "Temperatura agua alimentación", "Presión agua de alimentación",
                                "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"]
                    
                    df = pd.DataFrame(data)
                    df = df.iloc[:, :9] 
                    df.columns = cols_raw[:len(df.columns)]
                    df.insert(0, "FECHA", fecha_dt)
                    
                    # Calcular métricas (Esto crea las columnas "Tons.")
                    df = calcular_metricas(df, ini_vapor, ini_agua, ini_ingreso, ini_retorno)
                    
                    # --- REORDENAMIENTO EXACTO (MATCHING IMAGE) ---
                    orden_deseado = [
                        "FECHA", "HORA", 
                        "Totalizador de Vapor", "Tons. Vapor", 
                        "Temperatura de vapor", "Presión de Vapor",
                        "Totalizador agua alimentación", "Tons. Agua",
                        "Temperatura agua alimentación", "Presión agua de alimentación",
                        "Totalizador de báscula ingreso", "Tons. Biomasa Alim.",
                        "Totalizador de báscula de retorno", "Tons. Biomasa Ret."
                    ]
                    # Reindexamos para forzar el orden. Si falta alguna, pone 0.
                    df = df.reindex(columns=orden_deseado).fillna(0)
                    
                    st.session_state['df_final'] = df
                    st.rerun()
                except:
                    st.error("Error leyendo la imagen. Intenta otra.")

# --- RESULTADOS ---
if 'df_final' in st.session_state:
    st.divider()
    st.subheader("Tabla de Datos")
    st.caption("Los campos grises se calculan automáticamente.")

    cols_bloqueadas = ["Tons. Vapor", "Tons. Agua", "Tons. Biomasa Alim.", "Tons. Biomasa Ret.", "FECHA"]

    df_editado = st.data_editor(
        st.session_state['df_final'],
        disabled=cols_bloqueadas,
        num_rows="dynamic",
        key="editor_datos",
        use_container_width=True,
        height=500
    )

    # Detectar cambios para recalcular
    inputs = [c for c in df_editado.columns if c not in cols_bloqueadas]
    if not df_editado[inputs].equals(st.session_state['df_final'][inputs]):
        df_recalc = calcular_metricas(df_editado, ini_vapor, ini_agua, ini_ingreso, ini_retorno)
        # Asegurar orden de nuevo tras recalculo
        orden_deseado = [
            "FECHA", "HORA", 
            "Totalizador de Vapor", "Tons. Vapor", 
            "Temperatura de vapor", "Presión de Vapor",
            "Totalizador agua alimentación", "Tons. Agua",
            "Temperatura agua alimentación", "Presión agua de alimentación",
            "Totalizador de báscula ingreso", "Tons. Biomasa Alim.",
            "Totalizador de báscula de retorno", "Tons. Biomasa Ret."
        ]
        st.session_state['df_final'] = df_recalc[orden_deseado]
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
            
            # --- ESTILOS VISUALES ---
            # Header Amarillo (#FFFF00) con texto negro
            fmt_header = workbook.add_format({
                'bold': True, 
                'bg_color': '#FFFF00', # Amarillo Brillante
                'font_color': '#000000', # Texto Negro
                'border': 1,
                'align': 'center',
                'valign': 'vcenter'
            })
            fmt_date = workbook.add_format({'num_format': 'yyyy-mm-dd', 'border': 1, 'align': 'center'})
            fmt_cell = workbook.add_format({'border': 1, 'align': 'center'})
            
            for i, col in enumerate(df_editado.columns):
                worksheet.write(0, i, col, fmt_header)
                if col == "FECHA":
                    worksheet.set_column(i, i, 12, fmt_date)
                    worksheet.write_column(1, i, df_editado[col], fmt_date)
                else:
                    worksheet.set_column(i, i, 15, fmt_cell)

        st.download_button(
            label="📥 DESCARGAR EXCEL",
            data=buffer.getvalue(),
            file_name=nombre_archivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )