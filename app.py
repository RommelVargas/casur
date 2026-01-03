import streamlit as st
import pandas as pd
import google.generativeai as genai
from PIL import Image
import io
import json
import re
from datetime import datetime

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="CASUR - Digitalizador",
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
    # Temperatura baja para máxima precisión
    model = genai.GenerativeModel(
        model_name="models/gemini-2.5-flash",
        generation_config={"temperature": 0.1}
    )

# --- 3. FUNCIONES AUXILIARES ---
def clean_json_string(json_string):
    """Limpia la respuesta de la IA para sacar solo el JSON."""
    pattern = r'^```json\s*(.*?)\s*```$'
    match = re.search(pattern, json_string, re.DOTALL)
    if match:
        return match.group(1)
    return json_string

def get_gemini_response(image):
    """
    Lectura estricta basada en el formato físico de CASUR.
    Lee de Izquierda a Derecha las 9 columnas manuscritas.
    """
    prompt = """
    Tu tarea es transcribir la bitácora de generación de energía (CASUR).
    
    LA IMAGEN TIENE EXACTAMENTE 9 COLUMNAS CON DATOS MANUSCRITOS.
    Ignora los encabezados impresos, lee solo los números escritos a mano en azul.
    
    ORDEN EXACTO DE COLUMNAS (Izquierda a Derecha):
    1. [c1] HORA
    2. [c2] Totalizador de Vapor
    3. [c3] Temperatura de Vapor
    4. [c4] Presión de Vapor
    5. [c5] Totalizador Agua (Alimentación)
    6. [c6] Temperatura Agua
    7. [c7] Presión Agua
    8. [c8] Totalizador Báscula INGRESO (Bagacera) -> Penúltima columna
    9. [c9] Totalizador Báscula RETORNO (Bagacera) -> Última columna
    
    REGLAS:
    - La columna "Picadoras" NO suele tener datos, IGNÓRALA.
    - Devuelve un JSON Array.
    - Si un dato no se ve, pon 0.
    
    Ejemplo JSON:
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
    # Convertir a números
    cols_check = ["Totalizador de Vapor", "Totalizador agua alimentación",
                  "Totalizador de báscula ingreso", "Totalizador de báscula de retorno"]
    
    for col in cols_check:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Cálculos de Diferencias (Consumos)
    if "Totalizador de Vapor" in df.columns:
        df["Tons. Vapor"] = df["Totalizador de Vapor"].diff()
        if not df.empty and initials['vapor'] > 0:
            df.loc[0, "Tons. Vapor"] = df.loc[0, "Totalizador de Vapor"] - initials['vapor']

    if "Totalizador agua alimentación" in df.columns:
        df["Tons. Agua"] = df["Totalizador agua alimentación"].diff()
        if not df.empty and initials['agua'] > 0:
            df.loc[0, "Tons. Agua"] = df.loc[0, "Totalizador agua alimentación"] - initials['agua']

    if "Totalizador de báscula ingreso" in df.columns:
        df["Tons. Biomasa Alim."] = df["Totalizador de báscula ingreso"].diff()
        if not df.empty and initials['bagazo_in'] > 0:
            df.loc[0, "Tons. Biomasa Alim."] = df.loc[0, "Totalizador de báscula ingreso"] - initials['bagazo_in']

    if "Totalizador de báscula de retorno" in df.columns:
        df["Tons. Biomasa Ret."] = df["Totalizador de báscula de retorno"].diff()
        if not df.empty and initials['bagazo_out'] > 0:
            df.loc[0, "Tons. Biomasa Ret."] = df.loc[0, "Totalizador de báscula de retorno"] - initials['bagazo_out']
    
    return df

# --- 5. INTERFAZ GRÁFICA ---
st.title("🏭 CASUR - Digitalizador de Bitácoras")

if not api_key:
    st.error("⚠️ Falta la API Key en Secrets.")
    st.stop()

with st.sidebar:
    st.header("📋 Datos del Reporte")
    
    # --- AQUI ESTÁ LO QUE PEDISTE: FECHA ---
    fecha_reporte = st.date_input("Fecha de la Bitácora", datetime.now())
    
    st.header("🔢 Lecturas Iniciales (Ayer)")
    init_vapor = st.number_input("Vapor Inicial", value=0.0)
    init_agua = st.number_input("Agua Inicial", value=0.0)
    init_bagazo_in = st.number_input("Bagazo IN Inicial", value=0.0)
    init_bagazo_out = st.number_input("Bagazo RET Inicial", value=0.0)
    
    st.divider()
    uploaded_file = st.file_uploader("📸 Subir Foto Bitácora", type=["jpg", "png", "jpeg"])
    
    if st.button("🔄 Resetear Todo"):
        if 'data' in st.session_state: del st.session_state['data']
        st.rerun()

if uploaded_file and st.button("⚡ Procesar Imagen", type="primary"):
    img = Image.open(uploaded_file)
    st.image(img, use_column_width=True, caption="Imagen cargada")
    
    with st.spinner("Leyendo formato CASUR..."):
        raw_resp = get_gemini_response(img)
        
        # Debug oculto
        with st.expander("Ver lectura cruda (Solo si falla)", expanded=False):
            st.code(raw_resp)

        try:
            # 1. Limpieza JSON
            clean_txt = clean_json_string(raw_resp)
            if '[' in clean_txt:
                clean_txt = clean_txt[clean_txt.find('['):clean_txt.rfind(']')+1]
            
            data = json.loads(clean_txt)
            df = pd.DataFrame(data)

            # 2. RENOMBRAR EXACTO AL PAPEL DE CASUR
            mapa_casur = {
                "c1": "HORA",
                "c2": "Totalizador de Vapor",
                "c3": "Temperatura de vapor",
                "c4": "Presión de Vapor",
                "c5": "Totalizador agua alimentación",
                "c6": "Temperatura agua alimentación",
                "c7": "Presión agua de alimentación",
                "c8": "Totalizador de báscula ingreso",
                "c9": "Totalizador de báscula de retorno"
            }
            df = df.rename(columns=mapa_casur)

            # 3. AGREGAR LA FECHA (Tu petición)
            # Insertamos la columna FECHA en la posición 0 (al principio)
            df.insert(0, "FECHA", fecha_reporte)

            # 4. Calcular Métricas
            initials = {'vapor': init_vapor, 'agua': init_agua, 
                        'bagazo_in': init_bagazo_in, 'bagazo_out': init_bagazo_out}
            df_calc = calculate_metrics(df, initials)

            # 5. Orden Final para Excel
            columnas_finales = [
                "FECHA", "HORA", 
                "Totalizador de Vapor", "Tons. Vapor", 
                "Temperatura de vapor", "Presión de Vapor",
                "Totalizador agua alimentación", "Tons. Agua",
                "Temperatura agua alimentación", "Presión agua de alimentación",
                "Totalizador de báscula ingreso", "Tons. Biomasa Alim.",
                "Totalizador de báscula de retorno", "Tons. Biomasa Ret."
            ]
            # Reindexamos para ordenar y rellenar faltantes con 0
            df_final = df_calc.reindex(columns=columnas_finales).fillna(0)
            
            st.session_state['data'] = df_final
            st.rerun()

        except Exception as e:
            st.error(f"Error procesando: {e}")

# --- PANTALLA DE RESULTADOS ---
if 'data' in st.session_state:
    st.divider()
    st.subheader("✅ Datos Digitalizados")
    
    edited_df = st.data_editor(st.session_state['data'], num_rows="dynamic", use_container_width=True)
    
    st.write("---")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # --- AQUI ESTÁ LO QUE PEDISTE: NOMBRE DE ARCHIVO ---
        st.write("💾 **Opciones de Descarga**")
        nombre_default = f"Bitacora_{fecha_reporte}.xlsx"
        nombre_archivo = st.text_input("Nombre del archivo:", value=nombre_default)
        
        # Añadir extensión si el usuario la borró
        if not nombre_archivo.endswith(".xlsx"):
            nombre_archivo += ".xlsx"

        # Generar Excel Bonito
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name="Bitacora")
            workbook = writer.book
            worksheet = writer.sheets['Bitacora']
            
            # Estilos CASUR
            header_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'
            })
            date_fmt = workbook.add_format({'num_format': 'dd/mm/yyyy', 'border': 1, 'align': 'center'})
            cell_fmt = workbook.add_format({'border': 1, 'align': 'center'})
            
            for i, col in enumerate(edited_df.columns):
                worksheet.write(0, i, col, header_fmt)
                # Si es la columna de fecha (la primera), usar formato fecha
                if i == 0:
                    worksheet.set_column(i, i, 12, date_fmt)
                else:
                    worksheet.set_column(i, i, 15, cell_fmt)

        st.download_button(
            label="📥 Descargar Excel",
            data=buffer.getvalue(),
            file_name=nombre_archivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )