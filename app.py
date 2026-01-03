import streamlit as st
import pandas as pd
import google.generativeai as genai
from PIL import Image
import io
import json
import re
from datetime import datetime

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="CASUR Digital", layout="wide")

try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except:
    api_key = "" # Pega tu llave aquí entre comillas si pruebas en local

if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("models/gemini-2.5-flash", generation_config={"temperature": 0.1})

# --- FUNCIONES ---
def clean_json(text):
    """Limpia la respuesta para encontrar el JSON."""
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        return match.group(0)
    return text

def get_data_gemini(image):
    prompt = """
    Transcribe SOLO LOS NÚMEROS de esta tabla manuscrita.
    La tabla tiene 9 COLUMNAS DE DATOS (ignorando encabezados impresos).
    
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
    - Si la columna 10 (Picadoras) no se ve, IGNÓRALA.
    - Devuelve un JSON Array de listas (Arrays).
    - Ejemplo: [[ "07:00", 98000, 530, 85, 10000, 120, 110, 370000, 660000 ], ...]
    - Usa null o 0 si un dato es ilegible.
    """
    try:
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        return f"Error: {e}"

# --- INTERFAZ ---
st.title("🏭 CASUR - Digitalizador V3.0")

if not api_key:
    st.error("⚠️ Falta API Key")
    st.stop()

# BARRA LATERAL
with st.sidebar:
    st.header("1. Datos del Reporte")
    fecha_dt = st.date_input("Fecha del Turno", datetime.now())
    
    st.header("2. Lecturas Ayer (6:00 AM)")
    ini_vapor = st.number_input("Vapor Inicial", value=0.0)
    ini_agua = st.number_input("Agua Inicial", value=0.0)
    ini_ingreso = st.number_input("Ingreso Inicial", value=0.0)
    ini_retorno = st.number_input("Retorno Inicial", value=0.0)
    
    st.divider()
    archivo = st.file_uploader("Subir Foto", type=["jpg","png","jpeg","heic"])

# PROCESAMIENTO
if archivo and st.button("PROCESAR FOTO", type="primary"):
    img = Image.open(archivo)
    st.image(img, width=400)
    
    with st.spinner("Leyendo números..."):
        resp_raw = get_data_gemini(img)
        
        # --- ZONA DE DIAGNÓSTICO (Para ver si la IA responde) ---
        with st.expander("👁️ Ver lo que leyó la IA (Texto Crudo)", expanded=True):
            st.text(resp_raw)
        
        try:
            # 1. Limpiar y Convertir a DataFrame
            json_str = clean_json(resp_raw)
            data_list = json.loads(json_str)
            
            # Crear DF con nombres CASUR exactos
            cols = [
                "HORA", "Totalizador de Vapor", "Temperatura de vapor", "Presión de Vapor",
                "Totalizador agua alimentación", "Temperatura agua alimentación", "Presión agua de alimentación",
                "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"
            ]
            
            # Si la IA devolvió menos columnas, rellenamos; si más, cortamos
            df = pd.DataFrame(data_list)
            df = df.iloc[:, :9] # Asegurar max 9 columnas
            df.columns = cols[:len(df.columns)] # Asignar nombres disponibles

            # 2. AGREGAR FECHA (Tu petición)
            df.insert(0, "FECHA", fecha_dt)

            # 3. CÁLCULOS
            # Convertir a numérico
            num_cols = ["Totalizador de Vapor", "Totalizador agua alimentación", "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"]
            for c in num_cols:
                if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            
            # Diferencias
            if "Totalizador de Vapor" in df.columns:
                df["Tons. Vapor"] = df["Totalizador de Vapor"].diff()
                if len(df) > 0: df.loc[0, "Tons. Vapor"] = df.loc[0, "Totalizador de Vapor"] - ini_vapor

            if "Totalizador agua alimentación" in df.columns:
                df["Tons. Agua"] = df["Totalizador agua alimentación"].diff()
                if len(df) > 0: df.loc[0, "Tons. Agua"] = df.loc[0, "Totalizador agua alimentación"] - ini_agua

            if "Totalizador de báscula ingreso" in df.columns:
                df["Tons. Biomasa Alim."] = df["Totalizador de báscula ingreso"].diff()
                if len(df) > 0: df.loc[0, "Tons. Biomasa Alim."] = df.loc[0, "Totalizador de báscula ingreso"] - ini_ingreso

            if "Totalizador de báscula de retorno" in df.columns:
                df["Tons. Biomasa Ret."] = df["Totalizador de báscula de retorno"].diff()
                if len(df) > 0: df.loc[0, "Tons. Biomasa Ret."] = df.loc[0, "Totalizador de báscula de retorno"] - ini_retorno
            
            # Guardar en sesión
            st.session_state['df_final'] = df
            st.rerun()

        except Exception as e:
            st.error(f"Error procesando datos: {e}")

# RESULTADOS Y DESCARGA
if 'df_final' in st.session_state:
    st.divider()
    st.subheader("✅ Datos Verificados")
    edited_df = st.data_editor(st.session_state['df_final'], num_rows="dynamic")
    
    st.write("---")
    col1, col2 = st.columns(2)
    with col1:
        # --- TU PETICIÓN: NOMBRE DE ARCHIVO ---
        nombre_user = st.text_input("Nombre del archivo:", f"Bitacora_{fecha_dt}.xlsx")
        if not nombre_user.endswith(".xlsx"): nombre_user += ".xlsx"
        
        # Generar Excel
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name="Bitacora")
            workbook = writer.book
            worksheet = writer.sheets['Bitacora']
            fmt_header = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
            fmt_date = workbook.add_format({'num_format': 'dd/mm/yyyy', 'border': 1})
            
            for i, col in enumerate(edited_df.columns):
                worksheet.write(0, i, col, fmt_header)
                if col == "FECHA":
                    worksheet.set_column(i, i, 12, fmt_date)
                else:
                    worksheet.set_column(i, i, 15)
        
        st.download_button("📥 Descargar Excel", buffer.getvalue(), nombre_user, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")