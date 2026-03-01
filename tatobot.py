import streamlit as st
from google import genai
from google.generativeai import types
import pandas as pd
from pdf2image import convert_from_bytes
from PIL import Image
# Importamos io para manejar los datos del Excel en memoria
import io
import json
import re

# --- 1. CONFIGURACIÓN DE SEGURIDAD ---
# Intentamos obtener la clave desde los Secrets de Streamlit
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    # Inicializamos el nuevo cliente de Google GenAI
    client = genai.Client(api_key=API_KEY)
except Exception as e:
    st.error("⚠️ Error crítico: No se encontró la 'GOOGLE_API_KEY' en los Secrets.")
    st.stop()

# --- 2. LÓGICA DE NEGOCIO (FACTURAS A/B) ---
def aplicar_logica_iva(datos):
    """
    Si es Factura B, calculamos el neto y el IVA a partir del Total.
    Basado en los ejemplos de gastos analizados (ej: combustibles).
    """
    try:
        # Normalizamos el tipo de factura a mayúsculas
        tipo = str(datos.get("TIPO_FACTURA", "")).upper()
        
        # Intentamos obtener el total asegurándonos que sea un número
        total_str = str(datos.get("MONTO_TOTAL", "0")).replace(',', '.')
        total = float(re.findall(r"[-+]?\d*\.\d+|\d+", total_str)[0]) if total_str else 0
        
        # Si es Factura B, desglosamos el IVA 21% si no viene especificado
        if "B" in tipo:
            monto_gravado = datos.get("MONTO_GRAVADO")
            # Si el gravado está vacío o es igual al total, hacemos la cuenta
            if not monto_gravado or float(str(monto_gravado).replace(',','.')) == total:
                neto = round(total / 1.21, 2)
                iva = round(total - neto, 2)
                datos["MONTO_GRAVADO"] = neto
                datos["IVA_21"] = iva
        return datos
    except:
        return datos

# --- 3. FUNCIÓN DE PROCESAMIENTO ---
def procesar_archivo(file, prompt_usuario):
    try:
        # Convertir PDF a imagen si es necesario
        if file.type == "application/pdf":
            paginas = convert_from_bytes(file.read())
            imagen_final = paginas[0] # Tomamos la primera hoja
        else:
            imagen_final = Image.open(file)

        # Configuramos el Prompt con instrucciones estrictas
        prompt_sistema = f"""
        Actúa como un experto contable argentino. Analiza la imagen y extrae:
        TIPO_FACTURA, PUNTO_VENTA, NRO_FACTURA, CUIT_EMISOR, FECHA_EMISION, 
        RAZON_SOCIAL, MONTO_GRAVADO, IVA_27, IVA_21, IVA_10_5, PERCEPCION_IVA, 
        RETENCION_IVA, MONTO_NO_GRAVADO, MONTO_TOTAL.
        
        Instrucción adicional del usuario: {prompt_usuario}
        
        IMPORTANTE: Devuelve únicamente un objeto JSON válido. 
        No incluyas texto explicativo, ni marcas de código como ```json.
        """

        # Llamada a la nueva API de Google
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[prompt_sistema, imagen_final]
        )
        
        # Limpieza de la respuesta para asegurar que sea JSON puro
        texto_respuesta = response.text
        # Eliminamos posibles etiquetas de markdown que la IA a veces agrega
        texto_respuesta = texto_respuesta.replace("```json", "").replace("```", "").strip()
        
        data_json = json.loads(texto_respuesta)
        # Aplicamos la lógica de cálculo A/B
        data_json = aplicar_logica_iva(data_json)
        data_json["ARCHIVO_ORIGEN"] = file.name
        
        return data_json, None

    except Exception as e:
        # Devolvemos el diccionario con el nombre y el error detallado
        return {"ARCHIVO_ORIGEN": file.name}, str(e)

# --- 4. INTERFAZ DE USUARIO (STREAMLIT) ---
st.set_page_config(page_title="TatoBot AI", layout="wide")
st.title("📊 Extractor Inteligente de Facturas")
st.markdown("---")

# Barra lateral para configuraciones extra
with st.sidebar:
    st.header("⚙️ Opciones")
    extra = st.text_input("¿Dato adicional a buscar?", placeholder="Ej: Vencimiento, Patente")
    st.info("Desarrollado para procesamiento masivo de Compras y Ventas.")

# Pestañas de la aplicación
tab_compras, tab_ventas = st.tabs(["🛒 Compras / Gastos", "💰 Ventas / Ingresos"])

# --- LÓGICA DE COMPRAS ---
with tab_compras:
    st.subheader("Subir Facturas de Compras")
    u_compras = st.file_uploader("Arrastra aquí tus archivos", type=["pdf", "jpg", "png"], accept_multiple_files=True, key="comp")
    
    if st.button("Procesar Compras") and u_compras:
        resultados_ok = []
        errores_log = []
        progreso = st.progress(0)
        
        for idx, f in enumerate(u_compras):
            res, err = procesar_archivo(f, f"Foco en Proveedor. {extra}")
            if err:
                st.error(f"❌ Error en {f.name}: Ocurrió un error inesperado, contáctese con Tatito.")
                errores_log.append({"archivo": f.name, "error": err})
            else:
                resultados_ok.append(res)
            progreso.progress((idx + 1) / len(u_compras))
        
        if resultados_ok:
            df = pd.DataFrame(resultados_ok)
            st.write("### Vista previa de datos extraídos")
            st.dataframe(df)
            
            # Generación de Excel para descarga
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Compras')
            st.download_button("📥 Descargar Excel de Compras", buf.getvalue(), "compras_extraidas.xlsx")

        # Registro técnico para el dueño del proyecto (Tú)
        if errores_log:
            with st.expander("🛠️ Ver Detalle Técnico de Errores"):
                for e in errores_log:
                    st.code(f"Archivo: {e['archivo']}\nError: {e['error']}")

# --- LÓGICA DE VENTAS ---
with tab_ventas:
    st.subheader("Subir Facturas de Ventas")
    u_ventas = st.file_uploader("Arrastra aquí tus archivos", type=["pdf", "jpg", "png"], accept_multiple_files=True, key="vent")
    
    if st.button("Procesar Ventas") and u_ventas:
        resultados_ok = []
        errores_log = []
        progreso = st.progress(0)
        
        for idx, f in enumerate(u_ventas):
            res, err = procesar_archivo(f, f"Foco en Cliente y receptor. {extra}")
            if err:
                st.error(f"❌ Error en {f.name}: Ocurrió un error inesperado, contáctese con Tatito.")
                errores_log.append({"archivo": f.name, "error": err})
            else:
                resultados_ok.append(res)
            progreso.progress((idx + 1) / len(u_ventas))
            
        if resultados_ok:
            df_v = pd.DataFrame(resultados_ok)
            st.write("### Vista previa de ventas extraídas")
            st.dataframe(df_v)
            
            buf_v = io.BytesIO()
            with pd.ExcelWriter(buf_v, engine='xlsxwriter') as writer:
                df_v.to_excel(writer, index=False, sheet_name='Ventas')
            st.download_button("📥 Descargar Excel de Ventas", buf_v.getvalue(), "ventas_extraidas.xlsx")

        if errores_log:
            with st.expander("🛠️ Ver Detalle Técnico de Errores"):
                for e in errores_log:
                    st.code(f"Archivo: {e['archivo']}\nError: {e['error']}")