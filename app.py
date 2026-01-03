import streamlit as st
import pandas as pd
import google.generativeai as genai
from PIL import Image
import io
import json
import re

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="EGERSA - Digitalizador",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CONFIGURACIÓN DE API KEY ---
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except:
    api_key = ""

if api_key:
    genai.configure(api_key=api_key)
    # Usamos Flash, pero le subimos un pelín la temperatura para que sea más flexible
    model = genai.GenerativeModel(
        model_name="models/gemini-2.5-flash",
        generation_config={"temperature": 0.2}
    )

# --- 3. FUNCIONES AUXILIARES ---
def clean_json_string(json_string):
    """Limpia el texto basura que a veces manda la IA antes/después del JSON."""
    pattern = r'^```json\s*(.*?)\s*```$'
    match = re.search(pattern, json_string, re.DOTALL)
    if match:
        return match.group(1)
    return json_string

def get_gemini_response(image):
    """Estrategia POSICIONAL: Lee columna por columna sin importar el título."""
    prompt = """
    Actúa como un sistema OCR ciego. Tu único trabajo es extraer la tabla manuscrita.
    
    ESTRUCTURA VISUAL OBLIGATORIA:
    - La imagen tiene EXACTAMENTE 9 columnas visibles con datos manuscritos.
    - La tabla se corta a la derecha. NO inventes una décima columna.
    
    MAPEO POR POSICIÓN (Izquierda a Derecha):
    1. [c1] -> Hora
    2. [c2] -> Totalizador Vapor
    3. [c3] -> Temp Vapor
    4. [c4] -> Presion Vapor
    5. [c5] -> Totalizador Agua
    6. [c6] -> Temp Agua
    7. [c7] -> Presion Agua
    8. [c8] -> Totalizador Ingreso (Es la PENÚLTIMA columna visible)
    9. [c9] -> Totalizador Retorno (Es la ÚLTIMA columna visible)

    INSTRUCCIONES DE EXTRACCIÓN:
    - Devuelve un JSON Array donde cada objeto tenga las claves: "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9".
    - Si un número no es legible, pon 0.
    - NO añadas texto, solo el JSON.

    Ejemplo de salida:
    [
      {"c1": "07:00", "c2": 98523.2, "c3": 530, "c4": 85, "c5": 10306.5, "c6": 124, "c7": 117, "c8": 376992.0, "c9": 666565.0}
    ]
    """
    try:
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"

# --- 4. LÓGICA DE DATOS ---
def calculate_metrics(df, initials):
    # Definimos qué columnas esperamos que sean números
    cols_check = ["Totalizador de Vapor", "Totalizador agua alimentación",
                  "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"]
    
    for col in cols_check:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Cálculos
    if "Totalizador de Vapor" in df.columns:
        df["Tons. Vapor"] = df["Totalizador de Vapor"].diff()
        if not df.empty and initials['vapor'] > 0:
            df.loc[0, "Tons. Vapor"] = df.loc[0, "Totalizador de Vapor"] - initials['vapor']

    if "Totalizador agua alimentación" in df.columns:
        df["Tons. Agua"] = df["Totalizador agua alimentación"].diff()
        if not df.empty and initials['agua'] > 0:
            df.loc[0, "Tons. Agua"] = df.loc[0, "Totalizador agua alimentación"] - initials['agua']

    if "Totalizador de báscula ingreso" in df.columns:
        df["Toneladas biomasa Alimentación"] = df["Totalizador de báscula ingreso"].diff()
        if not df.empty and initials['bagazo_in'] > 0:
            df.loc[0, "Toneladas biomasa Alimentación"] = df.loc[0, "Totalizador de báscula ingreso"] - initials['bagazo_in']

    if "Totalizador de báscula de retorno" in df.columns:
        df["Toneladas Biomasa retorno"] = df["Totalizador de báscula de retorno"].diff()
        if not df.empty and initials['bagazo_out'] > 0:
            df.loc[0, "Toneladas Biomasa retorno"] = df.loc[0, "Totalizador de báscula de retorno"] - initials['bagazo_out']

    # Agregamos Picadoras manualmente (siempre 0 porque no sale en foto)
    df["Totalizador báscula de picadoras"] = 0
    df["Toneladas picadas"] = 0 
    
    return df

# --- 5. INTERFAZ ---
st.title("🏭 CaneVolt - Digitalizador V2.1 (Posicional)")

if not api_key:
    st.error("⚠️ No API Key found.")
    st.stop()

with st.sidebar:
    st.header("Valores Iniciales (Ayer)")
    init_vapor = st.number_input("Vapor Inicial", value=0.0)
    init_agua = st.number_input("Agua Inicial", value=0.0)
    init_bagazo_in = st.number_input("Bagazo IN Inicial", value=0.0)
    init_bagazo_out = st.number_input("Bagazo RET Inicial", value=0.0)
    st.divider()
    uploaded_file = st.file_uploader("Subir Foto", type=["jpg", "png", "jpeg"])
    if st.button("Resetear"):
        if 'data' in st.session_state: del st.session_state['data']
        st.rerun()

if uploaded_file and st.button("Procesar", type="primary"):
    img = Image.open(uploaded_file)
    st.image(img, use_column_width=True)
    
    with st.spinner("Analizando por posición de columnas..."):
        raw_resp = get_gemini_response(img)
        
        # --- ZONA DE DEPURACIÓN (Importante) ---
        with st.expander("🔍 Ver Datos Crudos (Si falla, mira aquí)", expanded=False):
            st.code(raw_resp, language='json')

        try:
            # 1. Limpieza
            clean_txt = clean_json_string(raw_resp)
            if '[' in clean_txt:
                clean_txt = clean_txt[clean_txt.find('['):clean_txt.rfind(']')+1]
            
            data = json.loads(clean_txt)
            df = pd.DataFrame(data)

            # 2. RENOMBRAR (Del c1..c9 a Nombres Reales)
            mapa = {
                "c1": "HORA",
                "c2": "Totalizador de Vapor",
                "c3": "Temperatura de vapor",
                "c4": "Presión de Vapor",
                "c5": "Totalizador agua alimentación",
                "c6": "Temperatura agua alimentación",
                "c7": "Presión agua de alimentación",
                "c8": "Totalizador de báscula ingreso",  # Aquí está el truco
                "c9": "Totalizador de báscula de retorno" # Y aquí
            }
            df = df.rename(columns=mapa)

            # 3. Calcular
            initials = {'vapor': init_vapor, 'agua': init_agua, 
                        'bagazo_in': init_bagazo_in, 'bagazo_out': init_bagazo_out}
            df_calc = calculate_metrics(df, initials)

            # 4. Ordenar Final
            orden = [
                "HORA", "Totalizador de Vapor", "Tons. Vapor", 
                "Temperatura de vapor", "Presión de Vapor",
                "Totalizador agua alimentación", "Tons. Agua",
                "Temperatura agua alimentación", "Presión agua de alimentación",
                "Totalizador de báscula ingreso", "Toneladas biomasa Alimentación",
                "Totalizador de báscula de retorno", "Toneladas Biomasa retorno",
                "Totalizador báscula de picadoras", "Toneladas picadas"
            ]
            # Usamos reindex para asegurar que todo exista
            df_final = df_calc.reindex(columns=orden).fillna(0)
            
            st.session_state['data'] = df_final
            st.rerun()

        except Exception as e:
            st.error(f"Error procesando: {e}")

# Mostrar Tabla Final
if 'data' in st.session_state:
    st.divider()
    edited_df = st.data_editor(st.session_state['data'], num_rows="dynamic", use_container_width=True)
    
    # Descarga Excel
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        edited_df.to_excel(writer, index=False, sheet_name="Bitacora")
        workbook = writer.book
        worksheet = writer.sheets['Bitacora']
        fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
        for i, col in enumerate(edited_df.columns):
            worksheet.write(0, i, col, fmt)
            worksheet.set_column(i, i, 18)
            
    st.download_button("📥 Descargar Excel", buffer.getvalue(), "Bitacora.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")