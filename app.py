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
    # Intenta leer de secrets (para la nube)
    api_key = st.secrets["GOOGLE_API_KEY"]
except:
    # Si falla, deja la variable vacía y muestra error luego
    api_key = ""

if api_key:
    genai.configure(api_key=api_key)
    # Usamos el modelo Flash que es rápido y bueno para tablas
    model = genai.GenerativeModel(
        model_name="models/gemini-2.5-flash",
        generation_config={
            "temperature": 0.1,
        }
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
    """Envía la imagen a Gemini con instrucciones blindadas para bordes cortados."""
    prompt = """
    Actúa como un digitador industrial experto. Transcribe esta bitácora manuscrita.
    
    CRÍTICO - GEOMETRÍA DE LA IMAGEN:
    1. La imagen puede estar rotada, léela en el sentido del texto manuscrito.
    2. ATENCIÓN: La hoja se corta físicamente a la derecha. 
    3. La ÚLTIMA columna visible en la foto suele ser "Retorno (bagacera)".
    4. NO busques la columna "Picadoras" si no se ve en el papel, ponle 0.

    COLUMNAS A EXTRAER (Orden Estricto de Izquierda a Derecha):
    1. HORA (Ej: 07:00... Lee lo que está escrito a mano)
    2. Totalizador de Vapor
    3. Temperatura de vapor
    4. Presión de Vapor
    5. Totalizador agua alimentación
    6. Temperatura agua alimentación
    7. Presión agua de alimentación
    8. Totalizador de báscula ingreso (Bagacera) -> Es la PENÚLTIMA columna visible.
    9. Totalizador de báscula de retorno (Bagacera) -> Es la ÚLTIMA columna visible a la derecha.
    10. Totalizador báscula de picadoras -> Pon siempre 0 (cero) si no se ve.

    Instrucciones de Lectura:
    - Los números son manuscritos en tinta azul.
    - Devuelve SOLO los datos numéricos, no texto extra.
    - Si un campo está vacío, pon null o 0.
    
    Salida esperada: ÚNICAMENTE un JSON Array válido.
    Ejemplo: [{"HORA": "07:00", "Totalizador de Vapor": 98523.2, ...}]
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
            # Convertimos a numérico, forzando errores a 0
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # --- CÁLCULOS (Actual - Anterior) ---
    # 1. Vapor
    if "Totalizador de Vapor" in df.columns:
        df["Tons. Vapor"] = df["Totalizador de Vapor"].diff()
        if not df.empty and initials['vapor'] > 0:
            df.loc[0, "Tons. Vapor"] = df.loc[0, "Totalizador de Vapor"] - initials['vapor']

    # 2. Agua
    if "Totalizador agua alimentación" in df.columns:
        df["Tons. Agua"] = df["Totalizador agua alimentación"].diff()
        if not df.empty and initials['agua'] > 0:
            df.loc[0, "Tons. Agua"] = df.loc[0, "Totalizador agua alimentación"] - initials['agua']

    # 3. Bagazo Entrada
    if "Totalizador de báscula ingreso" in df.columns:
        df["Toneladas biomasa Alimentación"] = df["Totalizador de báscula ingreso"].diff()
        if not df.empty and initials['bagazo_in'] > 0:
            df.loc[0, "Toneladas biomasa Alimentación"] = df.loc[0, "Totalizador de báscula ingreso"] - initials['bagazo_in']

    # 4. Bagazo Retorno
    if "Totalizador de báscula de retorno" in df.columns:
        df["Toneladas Biomasa retorno"] = df["Totalizador de báscula de retorno"].diff()
        if not df.empty and initials['bagazo_out'] > 0:
            df.loc[0, "Toneladas Biomasa retorno"] = df.loc[0, "Totalizador de báscula de retorno"] - initials['bagazo_out']

    # 5. Picadoras (Placeholder)
    df["Toneladas picadas"] = 0 

    return df

# --- 5. INTERFAZ GRÁFICA ---

st.title("Datos de Egersa")
st.markdown("Digitalización Inteligente de Bitácoras de Generación")

if not api_key:
    st.error("⚠️ No se detectó la API Key. Configúrala en los Secrets de Streamlit.")
    st.stop()

# --- SIDEBAR ---
with st.sidebar:
    st.header("1. Configuración Inicial (6:00 AM)")
    st.info("Datos del cierre de ayer para calcular la primera hora.")
    
    init_vapor = st.number_input("Lectura Vapor", value=0.0, format="%.2f")
    init_agua = st.number_input("Lectura Agua", value=0.0, format="%.2f")
    init_bagazo_in = st.number_input("Lectura Bagazo IN", value=0.0, format="%.2f")
    init_bagazo_out = st.number_input("Lectura Bagazo RET", value=0.0, format="%.2f")
    
    st.divider()
    st.header("2. Subir Bitácora")
    uploaded_file = st.file_uploader("Imagen (WhatsApp/Foto)", type=["jpg", "png", "heic", "jpeg"])
    
    if st.button("Resetear Todo"):
        if 'data' in st.session_state:
            del st.session_state['data']
        st.rerun()

# --- MAIN ---
if uploaded_file:
    img = Image.open(uploaded_file)
    with st.expander("Ver imagen original", expanded=False):
        st.image(img, use_column_width=True)
        
    process = st.button("Procesar Bitácora", type="primary")

    if process:
        with st.spinner("Gemini está leyendo los números..."):
            # 1. Obtener respuesta cruda
            response_text = get_gemini_response(img)
            
            # 2. Limpieza robusta del JSON
            try:
                # Usamos la función clean_json_string para quitar ```json
                cleaned_json = clean_json_string(response_text)
                
                # A veces Gemini devuelve texto plano antes del JSON, esto busca el primer '['
                if '[' in cleaned_json:
                    start = cleaned_json.find('[')
                    end = cleaned_json.rfind(']') + 1
                    cleaned_json = cleaned_json[start:end]

                data = json.loads(cleaned_json)
                df = pd.DataFrame(data)
                
                # 3. Calcular Diferencias
                initial_values = {
                    'vapor': init_vapor,
                    'agua': init_agua,
                    'bagazo_in': init_bagazo_in,
                    'bagazo_out': init_bagazo_out
                }
                df_calc = calculate_metrics(df, initial_values)
                
                # 4. Ordenar Columnas (Estándar CASUR)
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
                # Reindexamos para asegurar el orden, las columnas faltantes se rellenan con 0 o NaN
                df_final = df_calc.reindex(columns=final_order)
                
                st.session_state['data'] = df_final
                st.rerun()
                
            except json.JSONDecodeError:
                st.error("Error al interpretar los datos de la IA.")
                st.warning("Esto fue lo que envió la IA (copia esto para depurar):")
                st.code(response_text, language="text")
            except Exception as e:
                st.error(f"Error del sistema: {e}")

# --- RESULTADOS ---
if 'data' in st.session_state:
    st.divider()
    st.subheader("Datos Digitalizados")
    
    # Editor de datos interactivo
    edited_df = st.data_editor(
        st.session_state['data'],
        num_rows="dynamic",
        use_container_width=True,
        height=400
    )
    
    col1, col2 = st.columns(2)
    with col1:
        # Generador de Excel con xlsxwriter (Nativo, sin macros)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name="Bitacora")
            workbook = writer.book
            worksheet = writer.sheets['Bitacora']
            # Formatos básicos
            header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
            worksheet.set_column(0, 15, 18) # Ancho de columnas
            for col_num, value in enumerate(edited_df.columns.values):
                worksheet.write(0, col_num, value, header_fmt)

        st.download_button(
            label="📥 Descargar Excel",
            data=buffer.getvalue(),
            file_name="Bitacora_CASUR.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
    
    with col2:
        if not edited_df.empty:
            # Texto tabulado para copiar rápido
            st.info("Copia y Pega directo a tu Excel maestro:")
            # Se limpia un poco el formato para que pegue bien en Excel
            last_row_text = edited_df.iloc[-1].fillna(0).to_string(index=False, header=False).replace("\n", "\t")
            st.code(last_row_text, language="text")