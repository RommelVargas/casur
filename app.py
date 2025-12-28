import streamlit as st
import pandas as pd
import google.generativeai as genai
from PIL import Image
import io
import json

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="EGERSA",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CONFIGURACIÓN DE API KEY ---
try:
    # Intenta leer de secrets (para cuando lo subas a la nube)
    api_key = st.secrets["GOOGLE_API_KEY"]
except:
    # PEGA TU NUEVA API KEY AQUÍ PARA PRUEBAS LOCALES
    api_key = "AIzaSyAxgg3BwSPfXO0h0bAv03rqs4YuFFgpDTk"

genai.configure(api_key=api_key)

# Configuración del modelo (Usamos el 2.5 que es el que tienes activo)
model = genai.GenerativeModel(
    model_name="models/gemini-2.5-flash",
    generation_config={
        "temperature": 0.1,
        # "response_mime_type": "application/json" # Lo dejamos comentado por si acaso, haremos la limpieza manual
    }
)

# --- 3. LÓGICA DE IA (Gemini) ---
def get_gemini_response(image):
    """Envía la imagen a Gemini y pide SOLO las lecturas crudas."""
    prompt = """
    Actúa como un digitador experto en ingenios azucareros.
    Analiza esta imagen (puede ser una bitácora manuscrita o una tabla digital).
    
    TU MISIÓN:
    Extraer los datos numéricos de las columnas visibles.
    
    REGLAS CRÍTICAS:
    1. Si una columna no aparece en la imagen, devuélvela con valor 0.
    2. NO calcules diferencias (Tons), solo lee lo que ves.
    3. Devuelve SOLAMENTE un Array JSON válido. Sin texto extra, sin markdown.

    COLUMNAS A BUSCAR (Mapeo):
    1. HORA (Ej: 07:00)
    2. Totalizador de Vapor
    3. Temperatura de vapor
    4. Presión de Vapor
    5. Totalizador agua alimentación
    6. Temperatura agua alimentación
    7. Presión agua de alimentación
    8. Totalizador de báscula ingreso (Entrada Caña/Bagazo)
    9. Totalizador de báscula de retorno (Si existe)
    10. Totalizador báscula de picadoras (Si existe)

    Ejemplo de Salida JSON:
    [
    {
        "HORA": "07:00",
        "Totalizador de Vapor": 52863.5,
        "Temperatura de vapor": 524,
        "Presión de Vapor": 84,
        "Totalizador agua alimentación": 55320.7,
        ...
    }
    ]
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
            raw_response = get_gemini_response(img)
            
            # 2. LIMPIEZA CRÍTICA (Esto soluciona tu error anterior)
            # Eliminamos ```json, ``` y espacios extra
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            
            try:
                # 3. Parsear
                data = json.loads(clean_json)
                df = pd.DataFrame(data)
                
                # 4. Calcular
                initial_values = {
                    'vapor': init_vapor,
                    'agua': init_agua,
                    'bagazo_in': init_bagazo_in,
                    'bagazo_out': init_bagazo_out
                }
                df_calc = calculate_metrics(df, initial_values)
                
                # 5. Ordenar Columnas (Estándar CASUR)
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
                
            except json.JSONDecodeError:
                st.error("La IA se confundió con el formato.")
                st.warning("Respuesta técnica recibida:")
                st.code(raw_response, language="text")
            except Exception as e:
                st.error(f"Error del sistema: {e}")

# --- RESULTADOS ---
if 'data' in st.session_state:
    st.divider()
    st.subheader("Datos Digitalizados")
    
    edited_df = st.data_editor(
        st.session_state['data'],
        num_rows="dynamic",
        use_container_width=True,
        height=400
    )
    
    col1, col2 = st.columns(2)
    with col1:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name="Bitacora")
            
        st.download_button(
            label="📥 Descargar Excel",
            data=buffer.getvalue(),
            file_name="Bitacora_CASUR_Digitada.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
    
    with col2:
        if not edited_df.empty:
            # Texto tabulado para copiar directo a Excel
            last_row_text = edited_df.iloc[-1].fillna(0).to_string(index=False, header=False).replace("\n", "\t")
            st.text_area("Copiar Última Fila:", value=last_row_text, height=70)
            st.caption("Tip: Haz click en el cuadro, Ctrl+A, Ctrl+C y pega en tu Excel maestro.")