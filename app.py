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
    model = genai.GenerativeModel(
        model_name="models/gemini-2.5-flash",
        generation_config={"temperature": 0.1}
    )

# --- 3. LÓGICA DE IA (Gemini) ---
def clean_json_string(json_string):
    """Limpia el texto que devuelve Gemini para obtener solo el JSON puro."""
    pattern = r'^```json\s*(.*?)\s*```$'
    match = re.search(pattern, json_string, re.DOTALL)
    if match:
        return match.group(1)
    return json_string

def get_gemini_response(image):
    """Envía la imagen a Gemini usando CLAVES CORTAS para evitar errores de texto."""
    prompt = """
    Actúa como un digitador industrial experto. Transcribe esta bitácora manuscrita.
    
    CRÍTICO - GEOMETRÍA DE LA IMAGEN:
    1. La imagen puede estar rotada, léela en el sentido del texto manuscrito.
    2. ATENCIÓN: La hoja se corta físicamente a la derecha. 
    3. La PENÚLTIMA columna visible es "Ingreso".
    4. La ÚLTIMA columna visible es "Retorno".
    5. NO busques "Picadoras", ignórala.

    USA ESTAS CLAVES EXACTAS (JSON KEYS) PARA LOS DATOS:
    1. "hora"
    2. "vapor_tot"       (Totalizador de Vapor)
    3. "vapor_temp"      (Temperatura de vapor)
    4. "vapor_pres"      (Presión de Vapor)
    5. "agua_tot"        (Totalizador agua alimentación)
    6. "agua_temp"       (Temperatura agua alimentación)
    7. "agua_pres"       (Presión agua de alimentación)
    8. "ingreso"         (Totalizador de báscula ingreso - Bagacera)
    9. "retorno"         (Totalizador de báscula de retorno - Bagacera)
    10. "picadoras"      (Pon siempre 0)

    Instrucciones:
    - Devuelve SOLO números. Si está vacío o no se ve, pon 0.
    - Salida esperada: ÚNICAMENTE un JSON Array válido.
    
    Ejemplo: [{"hora": "07:00", "vapor_tot": 98523.2, "ingreso": 376992.0, "retorno": 666565.0}]
    """
    try:
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"

# --- 4. LÓGICA DE CÁLCULO (Python) ---
def calculate_metrics(df, initials):
    """Calcula las diferencias (Consumo) basándose en la fila anterior."""
    
    # Aseguramos que las columnas clave sean números
    cols_check = ["Totalizador de Vapor", "Totalizador agua alimentación",
                  "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"]
    
    for col in cols_check:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # --- CÁLCULOS ---
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

    df["Toneladas picadas"] = 0 
    return df

# --- 5. INTERFAZ GRÁFICA ---

st.title("🏭 CaneVolt - Digitalizador V2.0")

if not api_key:
    st.error("⚠️ No se detectó la API Key.")
    st.stop()

# --- SIDEBAR ---
with st.sidebar:
    st.header("1. Configuración Inicial")
    init_vapor = st.number_input("Lectura Vapor", value=0.0, format="%.2f")
    init_agua = st.number_input("Lectura Agua", value=0.0, format="%.2f")
    init_bagazo_in = st.number_input("Lectura Bagazo IN", value=0.0, format="%.2f")
    init_bagazo_out = st.number_input("Lectura Bagazo RET", value=0.0, format="%.2f")
    
    st.divider()
    uploaded_file = st.file_uploader("Subir Imagen", type=["jpg", "png", "heic", "jpeg"])
    
    if st.button("Resetear Todo"):
        if 'data' in st.session_state: del st.session_state['data']
        st.rerun()

# --- MAIN ---
if uploaded_file:
    img = Image.open(uploaded_file)
    with st.expander("Ver imagen original", expanded=False):
        st.image(img, use_column_width=True)
        
    if st.button("Procesar Bitácora", type="primary"):
        with st.spinner("Analizando..."):
            response_text = get_gemini_response(img)
            
            # DEPURACIÓN: Ver qué manda la IA si falla
            with st.expander("Ver respuesta cruda (Debugging)", expanded=False):
                st.code(response_text)

            try:
                # 1. Limpieza JSON
                cleaned_json = clean_json_string(response_text)
                if '[' in cleaned_json:
                    start = cleaned_json.find('[')
                    end = cleaned_json.rfind(']') + 1
                    cleaned_json = cleaned_json[start:end]

                data = json.loads(cleaned_json)
                df = pd.DataFrame(data)

                # 2. RENOMBRAMIENTO (La Magia para que no salga None)
                # Mapeamos las claves cortas de la IA a los nombres largos de CASUR
                mapa_nombres = {
                    "hora": "HORA",
                    "vapor_tot": "Totalizador de Vapor",
                    "vapor_temp": "Temperatura de vapor",
                    "vapor_pres": "Presión de Vapor",
                    "agua_tot": "Totalizador agua alimentación",
                    "agua_temp": "Temperatura agua alimentación",
                    "agua_pres": "Presión agua de alimentación",
                    "ingreso": "Totalizador de báscula ingreso",
                    "retorno": "Totalizador de báscula de retorno",
                    "picadoras": "Totalizador báscula de picadoras"
                }
                df = df.rename(columns=mapa_nombres)
                
                # 3. Calcular
                initial_values = {
                    'vapor': init_vapor, 'agua': init_agua,
                    'bagazo_in': init_bagazo_in, 'bagazo_out': init_bagazo_out
                }
                df_calc = calculate_metrics(df, initial_values)
                
                # 4. Ordenar
                final_order = [
                    "HORA",
                    "Totalizador de Vapor", "Tons. Vapor", 
                    "Temperatura de vapor", "Presión de Vapor",
                    "Totalizador agua alimentación", "Tons. Agua",
                    "Temperatura agua alimentación", "Presión agua de alimentación",
                    "Totalizador de báscula ingreso", "Toneladas biomasa Alimentación",
                    "Totalizador de báscula de retorno", "Toneladas Biomasa retorno",
                    "Totalizador báscula de picadoras", "Toneladas picadas"
                ]
                df_final = df_calc.reindex(columns=final_order)
                
                st.session_state['data'] = df_final
                st.rerun()
                
            except Exception as e:
                st.error(f"Error procesando: {e}")

# --- RESULTADOS ---
if 'data' in st.session_state:
    st.divider()
    edited_df = st.data_editor(st.session_state['data'], num_rows="dynamic", use_container_width=True)
    
    col1, col2 = st.columns(2)
    with col1:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name="Bitacora")
            workbook = writer.book
            worksheet = writer.sheets['Bitacora']
            header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
            for col_num, value in enumerate(edited_df.columns.values):
                worksheet.write(0, col_num, value, header_fmt)
                worksheet.set_column(col_num, col_num, 18)

        st.download_button("📥 Descargar Excel", buffer.getvalue(), "Bitacora_CASUR.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")