import streamlit as st
import google.generativeai as genai
import pandas as pd
from pdf2image import convert_from_bytes
import json
import io

# --- CONFIGURACIÓN DE SEGURIDAD ---
# En Streamlit Cloud, esto se configura en 'Settings > Secrets'
# En local, puedes usar st.secrets si creas el archivo .streamlit/secrets.toml
API_KEY = st.secrets["GOOGLE_API_KEY"]
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- LÓGICA DE EXTRACCIÓN ---
def process_image_with_ai(image, extra_fields=""):
    prompt = f"""
    Analiza esta imagen de un comprobante y extrae los datos en formato JSON.
    Campos base: TIPO_FACTURA, PUNTO_VENTA, NRO_FACTURA, CUIT_EMISOR, FECHA_EMISION, 
    RAZON_SOCIAL, MONTO_GRAVADO, IVA_21, MONTO_TOTAL.
    Campos adicionales solicitados: {extra_fields}
    
    IMPORTANTE: Devuelve SOLO el JSON, sin texto adicional ni bloques de código. 
    Si un campo no existe, pon null.
    """
    response = model.generate_content([prompt, image])
    try:
        # Limpieza por si la IA devuelve markdown
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except:
        return {"error": "No se pudo parsear la respuesta"}

# --- INTERFAZ DE USUARIO (UI) ---
st.set_page_config(page_title="Extractor de Documentos", layout="wide")
st.title("🚀 Extractor de Documentos Empresariales by Tatito")
st.markdown("Subime tus archivos y te lo devuelvo en un hermoso Excel. Comenzamos? 😉")

with st.sidebar:
    st.header("Configuración")
    campos_extra = st.text_input("Campos adicionales (separados por coma)", 
                                placeholder="Ej: Ingresos Brutos, Categoria")

uploaded_files = st.file_uploader("Arrastra tus PDFs o Imágenes aquí", 
                                  type=["pdf", "png", "jpg"], 
                                  accept_multiple_files=True)

if st.button("Procesar Documentos") and uploaded_files:
    all_results = []
    progress_bar = st.progress(0)
    
    for i, file in enumerate(uploaded_files):
        st.write(f"Procesando: {file.name}...")
        
        # Convertir PDF a Imagen si es necesario
        if file.type == "application/pdf":
            images = convert_from_bytes(file.read())
            # Procesamos la primera página para este ejemplo
            result = process_image_with_ai(images[0], campos_extra)
        else:
            # Es una imagen directa
            from PIL import Image
            img = Image.open(file)
            result = process_image_with_ai(img, campos_extra)
        
        result["archivo_origen"] = file.name
        all_results.append(result)
        progress_bar.progress((i + 1) / len(uploaded_files))

    # --- MOSTRAR RESULTADOS Y DESCARGA ---
    df = pd.DataFrame(all_results)
    st.success("¡Proceso completado!")
    st.dataframe(df)

    # Botón para descargar Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Resultados')
    
    st.download_button(
        label="📥 Descargar Reporte Excel",
        data=output.getvalue(),
        file_name="extraccion_facturas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )