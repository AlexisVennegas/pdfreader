import requests
from bs4 import BeautifulSoup
import os

SERPAPI_API_KEY = "39b077a27face11c565d5c7360b7b5544e8c7ab73994d626bd572953d61bfe98"

def buscar_pdf_empresa(empresa, query_extra="productos primarios filetype:pdf"):
    query = f"{empresa} {query_extra}"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_API_KEY,
        "num": 10
    }

    response = requests.get("https://serpapi.com/search", params=params)
    data = response.json()

    # Extraemos los enlaces que terminan en .pdf
    pdf_urls = []
    for result in data.get("organic_results", []):
        link = result.get("link", "")
        if link.endswith(".pdf"):
            pdf_urls.append(link)

    return pdf_urls


def descargar_pdf(url, carpeta_destino="pdfs_descargados"):
    os.makedirs(carpeta_destino, exist_ok=True)
    local_filename = os.path.join(carpeta_destino, url.split("/")[-1])

    try:
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            with open(local_filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return local_filename
    except Exception as e:
        print(f"Error al descargar {url}: {e}")
        return None


# Ejemplo de uso
empresa = "BASF SE"
pdfs = buscar_pdf_empresa(empresa)

print(f"PDFs encontrados para '{empresa}':")
for pdf in pdfs:
    print("→", pdf)

# Si encontramos al menos uno, lo descargamos
if pdfs:
    ruta = descargar_pdf(pdfs[0])
    print("PDF descargado en:", ruta)
else:
    print("No se encontró ningún PDF.")
