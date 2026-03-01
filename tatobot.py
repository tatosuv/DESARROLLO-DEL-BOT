import streamlit as st
from google import genai
from google.genai import types
import pandas as pd
from pdf2image import convert_from_bytes
from PIL import Image
import io
import json
import re

# --- 1. CONFIGURACIÓN DEL CLIENTE ---
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    # Inicializamos el cliente oficial
    client = genai.Client(api_key=API_KEY)
    # DEFINIMOS EL MODELO QUE VIMOS EN TU LISTA
    MODEL_ID = "gemini-2.0-flash-lite" 
except Exception as e:
    st.error("⚠️ Error: Configure su API KEY en los Secrets de Streamlit.")
    st.stop()

# --- 2. LÓGICA CONTABLE (FACTURAS A/B) ---
def aplicar_logica_iva(datos):
    try:
        tipo = str(datos.get("TIPO_FACTURA", "")).upper()
        
        def clean_num(val):
            if not val or val == "null": return 0.0
            # Limpieza profunda de strings a números
            s = str(val).replace('$', '').replace('.', '').replace(',', '.')
            res = re.findall(r"[-+]?\d*\.\d+|\d+", s)
            return float(res[0]) if res else 0.0

        total = clean_num(datos.get("MONTO_TOTAL"))
        
        if "B" in tipo:
            gravado = clean_num(datos.get("MONTO_GRAVADO"))
            if gravado == 0 or gravado == total:
                neto = round(total / 1.21, 2)
                iva = round(total - neto, 2)
                datos["MONTO_GRAVADO"] = neto
                datos["IVA_21"] = iva
        return datos
    except:
        return datos

# --- 3. FUNCIÓN DE EXTRACCIÓN ---
def procesar_archivo(file, prompt_usuario):
    try:
        if file.type == "application/pdf":
            paginas = convert_from_bytes(file.read())
            imagen_final = paginas[0]
        else:
            imagen_final = Image.open(file)

        prompt_sistema = f"""
        Eres un experto contable. Extrae estos campos en un JSON PURO:
        TIPO_FACTURA, PUNTO_VENTA, NRO_FACTURA, CUIT_EMISOR, FECHA_EMISION, 
        RAZON_SOCIAL, MONTO_GRAVADO, IVA_27, IVA_21, IVA_10_5, PERCEPCION_IVA, 
        RETENCION_IVA, MONTO_NO_GRAVADO, MONTO_TOTAL.
        
        Instrucción adicional: {prompt_usuario}
        
        IMPORTANTE: No escribas nada más que el objeto JSON. Sin ```json.
        """

        # Usamos el modelo gemini-2.0-flash que está en tu lista
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[prompt_sistema, imagen_final]
        )
        
        texto = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(texto)
        data = aplicar_logica_iva(data)
        data["ARCHIVO_ORIGEN"] = file.name
        return data, None
    except Exception as e:
        return {"ARCHIVO_ORIGEN": file.name}, str(e)

# --- 4. INTERFAZ DE USUARIO ---
st.set_page_config(page_title="TatoBot Pro", layout="wide")
st.title("📊 Extractor Contable TatoBot (v2.0 Flash)")

with st.sidebar:
    st.header("⚙️ Configuración")
    extra_field = st.text_input("Dato extra a buscar:", placeholder="Ej: Patente o IIBB")
    st.divider()
    st.write(f"**Modelo activo:** {MODEL_ID}")

tab_compras, tab_ventas = st.tabs(["🛒 Compras / Gastos", "💰 Ventas / Ingresos"])

# --- LÓGICA DE COMPRAS ---
with tab_compras:
    st.subheader("Módulo de Compras")
    u_compras = st.file_uploader("Subir Compras", type=["pdf","jpg","png"], accept_multiple_files=True, key="c")
    if st.button("Procesar Compras") and u_compras:
        res_ok, errores = [], []
        bar = st.progress(0)
        for idx, f in enumerate(u_compras):
            res, err = procesar_archivo(f, f"Foco en PROVEEDOR. {extra_field}")
            if err:
                st.error(f"Error en {f.name}: Contacte a su Tatito.")
                errores.append({"archivo": f.name, "error": err})
            else:
                res_ok.append(res)
            bar.progress((idx + 1) / len(u_compras))
            
        if res_ok:
            df = pd.DataFrame(res_ok)
            st.dataframe(df)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                df.to_excel(w, index=False)
            st.download_button("📥 Descargar Excel Compras", buf.getvalue(), "compras.xlsx")
        if errores:
            with st.expander("🛠️ Detalle Técnico"):
                st.write(errores)

# --- LÓGICA DE VENTAS ---
with tab_ventas:
    st.subheader("Módulo de Ventas")
    u_ventas = st.file_uploader("Subir Ventas", type=["pdf","jpg","png"], accept_multiple_files=True, key="v")
    if st.button("Procesar Ventas") and u_ventas:
        res_ok_v, errores_v = [], []
        bar_v = st.progress(0)
        for idx, f in enumerate(u_ventas):
            res, err = procesar_archivo(f, f"Foco en CLIENTE / RECEPTOR. {extra_field}")
            if err:
                st.error(f"Error en {f.name}: Contacte a su Tatito.")
                errores_v.append({"archivo": f.name, "error": err})
            else:
                res_ok_v.append(res)
            bar_v.progress((idx + 1) / len(u_ventas))
            
        if res_ok_v:
            df_v = pd.DataFrame(res_ok_v)
            st.dataframe(df_v)
            buf_v = io.BytesIO()
            with pd.ExcelWriter(buf_v, engine='xlsxwriter') as w:
                df_v.to_excel(w, index=False)
            st.download_button("📥 Descargar Excel Ventas", buf_v.getvalue(), "ventas.xlsx")
        if errores_v:
            with st.expander("🛠️ Detalle Técnico"):
                st.write(errores_v)