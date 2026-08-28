from flask import Flask, render_template, request, send_file
import requests
import os
import shutil
import subprocess
import zipfile
import io
import time
from pathlib import Path
from datetime import datetime

app = Flask(__name__)

# La SEC exige identificarse con un contacto real en el User-Agent.
# En el servidor se define con la variable de entorno SEC_USER_AGENT.
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "SEC Filing Scraper contacto@example.com"
)

SEC_HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Accept": "*/*"
}

OUTPUT_DIR = Path("downloads")
OUTPUT_DIR.mkdir(exist_ok=True)


# ==========================
# CACHÉ EN MEMORIA
# ==========================
#
# La SEC limita las peticiones y su índice
# solo cambia una vez al día, así que se
# guarda el resultado durante unas horas.

CACHE = {}

CACHE_TTL = 6 * 60 * 60


def cached(key, builder):

    now = time.time()

    entry = CACHE.get(key)

    if entry and now - entry[0] < CACHE_TTL:
        return entry[1]

    value = builder()

    CACHE[key] = (now, value)

    return value


def get_ticker_map():
    url = "https://www.sec.gov/files/company_tickers.json"

    r = requests.get(
        url,
        headers=SEC_HEADERS,
        timeout=30
    )

    r.raise_for_status()

    data = r.json()

    result = {}

    for item in data.values():

        ticker = item["ticker"].upper()

        result[ticker] = {
            "cik": str(item["cik_str"]).zfill(10),
            "name": item["title"]
        }

    return result


def get_submissions(cik):

    def download():

        url = (
            "https://data.sec.gov/submissions/"
            f"CIK{cik}.json"
        )

        r = requests.get(
            url,
            headers=SEC_HEADERS,
            timeout=30
        )

        r.raise_for_status()

        return r.json()

    return cached(
        f"submissions:{cik}",
        download
    )


def get_historical(name):

    def download():

        url = (
            "https://data.sec.gov/submissions/"
            + name
        )

        r = requests.get(
            url,
            headers=SEC_HEADERS,
            timeout=30
        )

        r.raise_for_status()

        return r.json()

    return cached(
        f"historical:{name}",
        download
    )


def get_filings(cik, form, start_year, end_year):

    data = get_submissions(cik)

    filings = []

    # ==========================
    # FILINGS RECIENTES
    # ==========================

    recent = data["filings"]["recent"]

    for i in range(len(recent["form"])):

        if recent["form"][i] != form:
            continue

        filing_date = recent["filingDate"][i]

        year = int(filing_date[:4])

        if start_year <= year <= end_year:

            filings.append({
                "form": form,
                "filing_date": filing_date,
                "report_date": recent["reportDate"][i],
                "accession": recent["accessionNumber"][i],
                "document": recent["primaryDocument"][i]
            })

    # ==========================
    # FILINGS HISTÓRICOS
    # ==========================

    historical_files = data["filings"].get(
        "files",
        []
    )

    for historical in historical_files:

        try:

            historical_data = get_historical(
                historical["name"]
            )

            forms = historical_data["form"]

            for i in range(len(forms)):

                if forms[i] != form:
                    continue

                filing_date = (
                    historical_data["filingDate"][i]
                )

                year = int(filing_date[:4])

                if start_year <= year <= end_year:

                    filings.append({
                        "form": form,
                        "filing_date": filing_date,
                        "report_date": (
                            historical_data[
                                "reportDate"
                            ][i]
                        ),
                        "accession": (
                            historical_data[
                                "accessionNumber"
                            ][i]
                        ),
                        "document": (
                            historical_data[
                                "primaryDocument"
                            ][i]
                        )
                    })

        except Exception as e:

            print(
                "Error leyendo archivo histórico:",
                historical["name"],
                e
            )

    # ==========================
    # ELIMINAR DUPLICADOS
    # ==========================

    unique = {}

    for filing in filings:

        unique[
            filing["accession"]
        ] = filing

    filings = list(
        unique.values()
    )

    # ==========================
    # ORDENAR
    # ==========================

    filings.sort(
        key=lambda x: x["filing_date"],
        reverse=True
    )

    return filings

def get_chrome():

    # 1. Ruta explícita (la que usa el servidor)
    explicit = os.environ.get("CHROME_PATH")

    if explicit and os.path.exists(explicit):
        return explicit

    # 2. Chromium instalado en Linux
    for name in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable"
    ]:

        found = shutil.which(name)

        if found:
            return found

    # 3. macOS
    for path in [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium"
    ]:

        if os.path.exists(path):
            return path

    return None


def filing_url(cik, filing):

    accession = filing["accession"].replace("-", "")

    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/"
        f"{accession}/"
        f"{filing['document']}"
    )


def create_pdf(ticker, cik, filing, temp_dir):

    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    import base64

    chrome = get_chrome()

    if not chrome:
        raise Exception("Google Chrome no encontrado.")

    year = filing["filing_date"][:4]

    form_name = filing["form"].replace(" ", "_")

    filename = (
        f"{ticker}_{year}_{form_name}_"
        f"{filing['accession'].replace('-', '')}.pdf"
    )

    pdf = Path(temp_dir) / filename

    html = Path(temp_dir) / (
        filename.replace(".pdf", ".html")
    )

    # URL original del filing
    filing_page = filing_url(cik, filing)

    # Descargar HTML
    r = requests.get(
        filing_page,
        headers=SEC_HEADERS,
        timeout=60
    )

    r.raise_for_status()

    soup = BeautifulSoup(
        r.content,
        "html.parser"
    )

    # ==================================================
    # DESCARGAR IMÁGENES DEL FILING
    # ==================================================

    image_dir = Path(temp_dir) / "images"

    image_dir.mkdir(
        exist_ok=True
    )

    image_counter = 0

    for img in soup.find_all("img"):

        src = img.get("src")

        if not src:
            continue

        # Convertir URL relativa en absoluta
        image_url = urljoin(
            filing_page,
            src
        )

        try:

            image_response = requests.get(
                image_url,
                headers=SEC_HEADERS,
                timeout=30
            )

            image_response.raise_for_status()

            content_type = (
                image_response.headers
                .get("Content-Type", "")
                .lower()
            )

            # Solo guardar imágenes reales
            if not content_type.startswith("image/"):
                continue

            image_counter += 1

            extension = ".png"

            if "jpeg" in content_type:
                extension = ".jpg"

            elif "gif" in content_type:
                extension = ".gif"

            elif "svg" in content_type:
                extension = ".svg"

            image_filename = (
                f"image_{image_counter}"
                f"{extension}"
            )

            image_path = (
                image_dir /
                image_filename
            )

            image_path.write_bytes(
                image_response.content
            )

            # Cambiar el src del HTML
            # para utilizar la imagen local
            img["src"] = (
                image_path.resolve()
                .as_uri()
            )

        except Exception as e:

            print(
                "No se pudo descargar imagen:",
                image_url,
                e
            )

    print(
        f"Imágenes descargadas: "
        f"{image_counter}"
    )

    # ==================================================
    # GUARDAR HTML MODIFICADO
    # ==================================================

    soup_html = str(soup)

    html.write_text(
        soup_html,
        encoding="utf-8"
    )

    # ==================================================
    # CREAR PDF CON CHROME
    # ==================================================

    command = [

        chrome,

        "--headless=new",

        "--disable-gpu",

        "--no-sandbox",

        "--disable-dev-shm-usage",

        "--hide-scrollbars",

        "--allow-file-access-from-files",

        "--allow-universal-access-from-files",

        "--run-all-compositor-stages-before-draw",

        "--print-to-pdf="
        + str(pdf.resolve()),

        "--print-to-pdf-no-header",

        "--virtual-time-budget=15000",

        "--user-agent="
        + SEC_HEADERS["User-Agent"],

        html.resolve().as_uri()
    ]

    result = subprocess.run(

        command,

        stdout=subprocess.PIPE,

        stderr=subprocess.PIPE,

        text=True,

        timeout=240
    )

    # El HTML temporal se elimina.
    # La carpeta temporal completa
    # también se elimina al terminar
    # gracias a TemporaryDirectory.

    html.unlink(
        missing_ok=True
    )

    if not pdf.exists():

        raise Exception(
            "No se pudo crear el PDF.\n"
            + result.stderr
        )

    return pdf


@app.route("/")
def index():

    return render_template(
        "index.html",
        current_year=datetime.now().year
    )


@app.route("/diag")
def diag():

    # Comprueba qué responde la SEC al servidor.
    # No muestra el email del User-Agent.

    report = {
        "chrome": get_chrome(),
        "user_agent_configured": (
            SEC_USER_AGENT
            != "SEC Filing Scraper contacto@example.com"
        ),
        "checks": {}
    }

    targets = {
        "www.sec.gov": (
            "https://www.sec.gov/files/"
            "company_tickers.json"
        ),
        "data.sec.gov": (
            "https://data.sec.gov/submissions/"
            "CIK0000320193.json"
        )
    }

    for name, url in targets.items():

        try:

            r = requests.get(
                url,
                headers=SEC_HEADERS,
                timeout=30
            )

            report["checks"][name] = {
                "status": r.status_code,
                "bytes": len(r.content),
                "body": (
                    ""
                    if r.status_code == 200
                    else r.text[:300]
                )
            }

        except Exception as e:

            report["checks"][name] = {
                "error": f"{type(e).__name__}: {str(e)[:200]}"
            }

    return report


@app.route("/search", methods=["POST"])
def search():

    ticker = request.form.get("ticker", "").strip().upper()

    start_year = int(
        request.form.get(
            "start_year",
            datetime.now().year - 9
        )
    )

    end_year = int(
        request.form.get(
            "end_year",
            datetime.now().year
        )
    )

    forms = request.form.getlist("forms")

    if not forms:
        return render_template(
            "index.html",
            current_year=datetime.now().year,
            ticker=ticker,
            error="Select at least one form type to continue."
        )

    try:

        ticker_map = get_ticker_map()

    except requests.HTTPError as e:

        status = e.response.status_code if e.response is not None else "?"

        return render_template(
            "index.html",
            current_year=datetime.now().year,
            ticker=ticker,
            error=(
                f"EDGAR rejected the request (HTTP {status}). "
                "Check the SEC_USER_AGENT setting."
            )
        )

    except Exception as e:

        return render_template(
            "index.html",
            current_year=datetime.now().year,
            ticker=ticker,
            error=f"Could not reach EDGAR: {type(e).__name__}"
        )

    if ticker not in ticker_map:
        return render_template(
            "index.html",
            current_year=datetime.now().year,
            ticker=ticker,
            error=f"Ticker {ticker} not found on EDGAR."
        )

    company = ticker_map[ticker]

    all_filings = []

    for form in forms:

        try:

            filings = get_filings(
                company["cik"],
                form,
                start_year,
                end_year
            )

            all_filings.extend(filings)

        except Exception as e:

            print(
                f"Error obteniendo {form}: {e}"
            )

    # Eliminar duplicados
    unique = {}

    for filing in all_filings:

        unique[
            filing["accession"]
        ] = filing

    all_filings = list(
        unique.values()
    )

    # Ordenar por fecha
    all_filings.sort(
        key=lambda x: x["filing_date"],
        reverse=True
    )

    return render_template(
        "results.html",
        ticker=ticker,
        company=company["name"],
        cik=company["cik"],
        current_year=datetime.now().year,
        start_year=start_year,
        end_year=end_year,
        filings=all_filings
    )

@app.route(
    "/download",
    methods=["POST"]
)
def download():

    ticker = request.form.get(
        "ticker",
        ""
    ).strip().upper()

    accession_list = request.form.getlist(
        "accession"
    )

    if not accession_list:
        return "No seleccionaste ningún filing.", 400

    ticker_map = get_ticker_map()

    if ticker not in ticker_map:
        return "Ticker no encontrado", 404

    company = ticker_map[ticker]

    # Obtener todos los filings disponibles
    # para localizar los accession seleccionados.
    filing_types = [
        "10-K",
        "10-Q",
        "8-K",
        "DEF 14A",
        "20-F",
        "6-K",
        "S-1",
        "S-3",
        "S-4",
        "3",
        "4",
        "5"
    ]

    all_filings = []

    for form_type in filing_types:

        try:

            filings = get_filings(
                company["cik"],
                form_type,
                1990,
                datetime.now().year
            )

            all_filings.extend(
                filings
            )

        except Exception as e:

            print(
                f"Error obteniendo {form_type}: {e}"
            )

    selected = [
        filing
        for filing in all_filings
        if filing["accession"]
        in accession_list
    ]

    if not selected:
        return (
            "No se encontraron "
            "los filings seleccionados.",
            404
        )

    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:

        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(
            zip_buffer,
            "w",
            zipfile.ZIP_DEFLATED
        ) as z:

            for filing in selected:

                pdf = create_pdf(
                    ticker,
                    company["cik"],
                    filing,
                    temp_dir
                )

                z.write(
                    pdf,
                    pdf.name
                )

        zip_buffer.seek(0)

        # Crear nombre según los tipos
        selected_forms = sorted(
            set(
                filing["form"]
                for filing in selected
            )
        )

        forms_name = "-".join(
            selected_forms
        )

        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=(
                f"{ticker}_"
                f"{forms_name}_"
                "filings.zip"
            ),
            mimetype="application/zip"
        )
if __name__ == "__main__":

    print()
    print(
        "SEC Filing Scraper"
    )
    print(
        "http://127.0.0.1:5000"
    )
    print()

    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 8000)),
        debug=True
    )