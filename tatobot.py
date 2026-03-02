import streamlit as st
from google import genai
import pandas as pd
from pdf2image import convert_from_bytes
from PIL import Image
import io
import json
import re

# --- CONFIGURACIÓN ---
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    client = genai.Client(api_key=API_KEY)
    # Usamos el modelo que te funcionó
    MODEL_ID = "gemini-2.5-flash-lite" 
except Exception as e:
    st.error("⚠️ Configura la API KEY en los Secrets.")
    st.stop()

def aplicar_logica_contable(datos):
    """Asegura que los montos sean numéricos y aplica lógica A/B"""
    try:
        def to_f(v):
            if v is None or str(v).lower() == "null": return 0.0
            s = str(v).replace('$', '').replace('.', '').replace(',', '.')
            res = re.findall(r"[-+]?\d*\.\d+|\d+", s)
            return float(res[0]) if res else 0.0

        datos["MONTO_TOTAL"] = to_f(datos.get("MONTO_TOTAL"))
        datos["MONTO_GRAVADO"] = to_f(datos.get("MONTO_GRAVADO"))
        datos["IVA_21"] = to_f(datos.get("IVA_21"))
        
        # Lógica de Factura B: si el gravado es igual al total y hay IVA implícito
        if "B" in str(datos.get("TIPO_FACTURA", "")).upper():
            if datos["MONTO_GRAVADO"] == 0 or datos["MONTO_GRAVADO"] == datos["MONTO_TOTAL"]:
                datos["MONTO_GRAVADO"] = round(datos["MONTO_TOTAL"] / 1.21, 2)
                datos["IVA_21"] = round(datos["MONTO_TOTAL"] - datos["MONTO_GRAVADO"], 2)
        
        return datos
    except:
        return datos

def procesar_archivo(file, instruccion_extra):
    resultados_archivo = []
    try:
        # 1. Convertir todas las páginas
        if file.type == "application/pdf":
            paginas = convert_from_bytes(file.read())
        else:
            paginas = [Image.open(file)]

        for i, img in enumerate(paginas):
            prompt = f"""
            Eres un experto contable argentino. Analiza la imagen y extrae TODOS los comprobantes que veas.
            Si hay más de uno, devuelve una lista de objetos JSON.
            
            Campos requeridos por cada comprobante:
            - TIPO_FACTURA: (A, B, C, M, Ticket, etc)
            - PUNTO_VENTA: Solo los 4 o 5 dígitos antes del guión.
            - NRO_FACTURA: Solo los 8 dígitos después del guión.
            - CUIT_EMISOR: Con guiones.
            - FECHA_EMISION: DD/MM/AAAA.
            - RAZON_SOCIAL: Nombre del emisor.
            - MONTO_GRAVADO: Neto sin impuestos.
            - IVA_21: Monto del IVA al 21%.
            - MONTO_NO_GRAVADO: Si hay conceptos que no sabes dónde ubicar o son 'No Gravados', ponlos aquí.
            - MONTO_TOTAL: Total final.

            {instruccion_extra}

            IMPORTANTE: Devuelve unicamente una lista de JSON: [{{...}}, {{...}}].
            Si no encuentras nada, devuelve [].
            """

            response = client.models.generate_content(model=MODEL_ID, contents=[prompt, img])
            
            # Limpiar y parsear (la IA puede devolver un objeto o una lista)
            texto = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(texto)
            
            if isinstance(data, dict): data = [data] # Normalizar a lista
            
            for item in data:
                item = aplicar_logica_contable(item)
                item["HOJA"] = i + 1
                item["ARCHIVO"] = file.name
                resultados_archivo.append(item)
                
        return resultados_archivo, None
    except Exception as e:
        return [], str(e)

# --- INTERFAZ ---
st.set_page_config(page_title="TatoBot Pro", layout="wide")
st.title("🚀 Extractor Contable Multipage v3.0")

tab_comp, tab_vent = st.tabs(["🛒 Compras", "💰 Ventas"])

def render_modulo(key, label):
    st.subheader(f"Procesar {label}")
    u_files = st.file_uploader(f"Subir {label}", type=["pdf","jpg","png"], accept_multiple_files=True, key=key)
    if st.button(f"Ejecutar {label}") and u_files:
        final_data = []
        bar = st.progress(0)
        for idx, f in enumerate(u_files):
            # Instrucción específica para separar PV y NRO
            extra = "SEPARA estrictamente PUNTO_VENTA (4-5 nros) de NRO_FACTURA (8 nros). No los mezcles."
            res, err = procesar_archivo(f, extra)
            if err: st.error(f"Error en {f.name}: {err}")
            else: final_data.extend(res)
            bar.progress((idx + 1) / len(u_files))
        
        if final_data:
            df = pd.DataFrame(final_data)
            st.dataframe(df)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                df.to_excel(w, index=False)
            st.download_button(f"📥 Descargar Excel {label}", buf.getvalue(), f"{label.lower()}.xlsx")

with tab_comp: render_modulo("c", "Compras")
with tab_vent: render_modulo("v", "Ventas")