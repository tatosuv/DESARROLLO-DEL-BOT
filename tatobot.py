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
    MODEL_ID = "gemini-2.5-flash-lite" 
except Exception as e:
    st.error("⚠️ Error de configuración.")
    st.stop()

def limpiar_monto_argentino(valor):
    """
    Convierte montos tipo '3.914,96' a float 3914.96 de forma segura.
    """
    if valor is None or str(valor).lower() == "null" or valor == "":
        return 0.0
    
    s = str(valor).strip().replace('$', '').replace(' ', '')
    
    # Si tiene punto y coma (ej: 1.234,56)
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    # Si solo tiene coma (ej: 1234,56)
    elif ',' in s:
        s = s.replace(',', '.')
    # Si tiene un punto que parece de miles (ej: 1.234) pero no hay decimales
    # Esto es arriesgado, pero en facturas el punto suele ser mil.
    
    try:
        # Extraer solo el número con su decimal
        res = re.findall(r"[-+]?\d*\.\d+|\d+", s)
        return float(res[0]) if res else 0.0
    except:
        return 0.0

def procesar_archivo(file, instruccion_extra):
    resultados_archivo = []
    try:
        if file.type == "application/pdf":
            # Reducimos la resolución (DPI) para ganar velocidad sin perder mucha calidad
            paginas = convert_from_bytes(file.read(), dpi=150)
        else:
            paginas = [Image.open(file)]

        for i, img in enumerate(paginas):
            # Usamos un mensaje de estado para el usuario
            with st.status(f"Analizando {file.name} - Página {i+1}...", expanded=False) as status:
                prompt = f"""
                Eres un extractor de datos contables preciso. 
                Analiza la imagen y busca TODOS los comprobantes.
                
                Reglas de Oro:
                1. PUNTO_VENTA: Los dígitos antes del guión (ej: de 02019-00048381, extrae '02019').
                2. NRO_FACTURA: Los 8 dígitos después del guión.
                3. Extrae los montos tal cual aparecen (con comas o puntos).
                
                Campos a extraer:
                TIPO_FACTURA, PUNTO_VENTA, NRO_FACTURA, CUIT_EMISOR, FECHA_EMISION, 
                RAZON_SOCIAL, MONTO_GRAVADO, IVA_21, IVA_10_5, PERCEPCION_IVA, MONTO_TOTAL.

                {instruccion_extra}

                Devuelve UNA LISTA de JSON: [{{...}}, {{...}}]
                Si la respuesta es muy larga, simplifica la RAZON_SOCIAL.
                """

                response = client.models.generate_content(model=MODEL_ID, contents=[prompt, img])
                
                try:
                    texto = response.text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(texto)
                    if isinstance(data, dict): data = [data]
                    
                    for item in data:
                        # --- LIMPIEZA Y LÓGICA MATEMÁTICA ---
                        g = limpiar_monto_argentino(item.get("MONTO_GRAVADO"))
                        i21 = limpiar_monto_argentino(item.get("IVA_21"))
                        i105 = limpiar_monto_argentino(item.get("IVA_10_5"))
                        per = limpiar_monto_argentino(item.get("PERCEPCION_IVA"))
                        total = limpiar_monto_argentino(item.get("MONTO_TOTAL"))
                        
                        # Calculamos el No Gravado por diferencia (Fórmula solicitada)
                        # No Gravado = Total - (Gravado + IVA21 + IVA105 + Percepcion)
                        no_gravado = round(total - (g + i21 + i105 + per), 2)
                        
                        # Guardamos los valores finales limpios
                        item["MONTO_GRAVADO"] = g
                        item["IVA_21"] = i21
                        item["IVA_10_5"] = i105
                        item["PERCEPCION_IVA"] = per
                        item["MONTO_NO_GRAVADO"] = no_gravado if no_gravado > 0.01 else 0.0
                        item["MONTO_TOTAL"] = total
                        
                        item["ARCHIVO"] = file.name
                        item["PAG"] = i + 1
                        resultados_archivo.append(item)
                    
                    status.update(label=f"Página {i+1} completada", state="complete")
                except Exception as e:
                    st.error(f"Error parseando JSON en pág {i+1}: {e}")
                    continue
                
        return resultados_archivo, None
    except Exception as e:
        return [], str(e)

# --- INTERFAZ ---
st.set_page_config(page_title="TatoBot v4", layout="wide")
st.title("📊 TatoBot AI: Extractor Contable Premium")

u_files = st.file_uploader("Subir Compras/Ventas", type=["pdf","jpg","png"], accept_multiple_files=True)

if st.button("🚀 Ejecutar Procesamiento Masivo") and u_files:
    all_results = []
    main_bar = st.progress(0)
    
    # Contenedor para ver el progreso
    for idx, f in enumerate(u_files):
        res, err = procesar_archivo(f, "Extrae montos con sus decimales originales.")
        if err:
            st.error(f"Error crítico en {f.name}: {err}")
        else:
            all_results.extend(res)
        
        main_bar.progress((idx + 1) / len(u_files))
    
    if all_results:
        df = pd.DataFrame(all_results)
        st.success(f"✅ Procesados {len(all_results)} comprobantes con éxito.")
        
        # Reordenar columnas para que sea cómodo
        cols = ["ARCHIVO", "PAG", "FECHA_EMISION", "RAZON_SOCIAL", "TIPO_FACTURA", "PUNTO_VENTA", "NRO_FACTURA", 
                "MONTO_GRAVADO", "IVA_21", "IVA_10_5", "PERCEPCION_IVA", "MONTO_NO_GRAVADO", "MONTO_TOTAL"]
        df = df[cols]
        
        st.dataframe(df)
        
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
            df.to_excel(w, index=False)
        st.download_button("📥 Descargar Excel Final", buf.getvalue(), "extraccion_tatobot.xlsx")