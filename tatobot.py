import streamlit as st
import google.generativeai as genai
import pandas as pd
from pdf2image import convert_from_bytes
from PIL import Image
import json
import io
import re

# --- CONFIGURACIÓN DE SEGURIDAD ---
# Se extrae de la pestaña 'Secrets' 
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error("Error: No se encontró la API KEY en los Secrets de Streamlit.")
    st.stop()

# --- LÓGICA DE NEGOCIO: CÁLCULOS CONTABLES ---
def aplicar_logica_iva(datos):
    """
    Si es Factura B, calculamos el neto y el IVA a partir del Total
    asumiendo una alícuota del 21% si no está especificada.
    """
    try:
        tipo = str(datos.get("TIPO_FACTURA", "")).upper()
        total = float(str(datos.get("MONTO_TOTAL", 0)).replace(',', '.'))
        
        if "B" in tipo:
            # Si el gravado es nulo o igual al total, hacemos el desglose manual
            gravado = float(str(datos.get("MONTO_GRAVADO", 0)).replace(',', '.'))
            if gravado == 0 or gravado == total:
                neto = round(total / 1.21, 2)
                iva = round(total - neto, 2)
                datos["MONTO_GRAVADO"] = neto
                datos["IVA_21"] = iva
        
        return datos
    except:
        return datos

# --- FUNCIÓN MAESTRA DE EXTRACCIÓN ---
def procesar_archivo(file, prompt_especifico):
    # 1. Convertir PDF a imagen si es necesario
    if file.type == "application/pdf":
        paginas = convert_from_bytes(file.read())
        imagen_para_ai = paginas[0] # Procesamos la primera página
    else:
        imagen_para_ai = Image.open(file)

    # 2. Llamada a la IA
    full_prompt = f"""
    Eres un experto contable argentino. Analiza la imagen y extrae los datos en un JSON estricto.
    Campos base: 
    TIPO_FACTURA, PUNTO_VENTA, NRO_FACTURA, CUIT_EMISOR, FECHA_EMISION, 
    RAZON_SOCIAL, MONTO_GRAVADO, IVA_27, IVA_21, IVA_10_5, PERCEPCION_IVA, 
    RETENCION_IVA, MONTO_NO_GRAVADO, MONTO_TOTAL.
    
    {prompt_especifico}
    
    Devuelve SOLO el objeto JSON. Si un dato no está, usa null.
    """
    
    response = model.generate_content([full_prompt, imagen_para_ai])
    
    # 3. Limpieza de respuesta y conversión a diccionario
    try:
        texto_limpio = re.sub(r'```json|```', '', response.text).strip()
        data_json = json.loads(texto_limpio)
        # Aplicamos la lógica de Factura A/B
        data_json = aplicar_logica_iva(data_json)
        data_json["ARCHIVO"] = file.name
        return data_json
    except Exception as e:
        return {"ARCHIVO": file.name, "ERROR": "Error al procesar formato JSON"}

# --- INTERFAZ STREAMLIT ---
st.set_page_config(page_title="TatoBot Contable", layout="wide")
st.title("📊 Automatización Contable Pro")

with st.sidebar:
    st.header("⚙️ Configuración")
    campos_extra = st.text_input("Campos adicionales (ej: IIBB, Vencimiento)", "")
    st.divider()
    st.info("Sube tus archivos en la pestaña correspondiente.")

tab_compras, tab_ventas = st.tabs(["🛒 Compras / Gastos", "💰 Ventas / Ingresos"])

# --- LÓGICA PARA PESTAÑA COMPRAS ---
with tab_compras:
    st.subheader("Procesar Facturas de Compra")
    files_compras = st.file_uploader("Subir comprobantes de compra", type=["pdf", "jpg", "png"], accept_multiple_files=True, key="u_compras")
    
    if st.button("Ejecutar Extracción Compras") and files_compras:
        resultados = []
        barra = st.progress(0)
        
        for i, f in enumerate(files_compras):
            res = procesar_archivo(f, f"Foco en: Proveedor y CUIT emisor. {campos_extra}")
            resultados.append(res)
            barra.progress((i + 1) / len(files_compras))
        
        df_compras = pd.DataFrame(resultados)
        st.dataframe(df_compras)
        
        # Descarga
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            df_compras.to_excel(writer, index=False)
        st.download_button("📥 Descargar Excel Compras", out.getvalue(), "compras.xlsx")

# --- LÓGICA PARA PESTAÑA VENTAS ---
with tab_ventas:
    st.subheader("Procesar Facturas de Venta")
    files_ventas = st.file_uploader("Subir comprobantes de venta", type=["pdf", "jpg", "png"], accept_multiple_files=True, key="u_ventas")
    
    if st.button("Ejecutar Extracción Ventas") and files_ventas:
        resultados = []
        barra = st.progress(0)
        
        for i, f in enumerate(files_ventas):
            res = procesar_archivo(f, f"Foco en: Cliente y datos del receptor. {campos_extra}")
            resultados.append(res)
            barra.progress((i + 1) / len(files_ventas))
            
        df_ventas = pd.DataFrame(resultados)
        st.dataframe(df_ventas)
        
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            df_ventas.to_excel(writer, index=False)
        st.download_button("📥 Descargar Excel Ventas", out.getvalue(), "ventas.xlsx")