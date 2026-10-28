from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (
    NoAlertPresentException,
    StaleElementReferenceException,
    UnexpectedAlertPresentException,
)
from dotenv import load_dotenv
from datetime import datetime, date, timedelta
import json
import os
import re
import sys
import time

# CONSTANTES MODIFICABLES
HORAS_A_RELLENAR = 5  # Horas totales a repartir cada día (QBid no deja pasar de las "Hores màximes")
# Se actualiza sola al final de cada ejecución con el último día registrado.
FECHA_INICIO_STR = "01/09/2026"  # Formato: DD/MM/YYYY
# La fecha final es siempre el día actual.

# CONSTANTES FIJAS
URL_LOGIN = "https://www.empresaiformacio.org/sBid"
PASO_MINUTOS = 15           # Granularidad de los desplegables (15min, 30min, ...)
TIMEOUT_RED = 30            # Máximo de segundos esperando respuestas HTTP
QUIETUD_RED = 0.6           # Segundos sin peticiones abiertas para dar la red por terminada
TIMEOUT_LOGIN_MANUAL = 180  # Si no hay credenciales, tiempo para iniciar sesión a mano
MAX_DIAS_SIN_TAREA = 10     # Días seguidos sin "Activitat diària" (festivos...) antes de rendirse

# Selectores de QBid (sacados de la web real)
CSS_CABECERA_MES = "#popupAgenda_calHeader0"                 # "octubre 2026"
CSS_ENLACE_DOSSIER = "#tablaTasquesDia a[href*='ActivitatFct']"
CSS_SELECTS_HORAS = "select[id^='inp_'][title='Valoracio']"  # Excluye los de ausencias
CSS_BOTON_GUARDAR = "span.btn[title='Emmagatzemar']"
XPATH_FLECHA_SIGUIENTE = "//img[@title='Següent' or contains(@src, 'nextAlumne')]/parent::a"
XPATH_MENU_AGENDA = "//a[normalize-space()='Agenda']"

load_dotenv()
QBID_USER = os.getenv("QBID_USER", "").strip()
QBID_PASSWD = os.getenv("QBID_PASSWD", "").strip()

fecha_inicio = datetime.strptime(FECHA_INICIO_STR, "%d/%m/%Y").date()
fecha_final = date.today()
MINUTOS_OBJETIVO = int(round(HORAS_A_RELLENAR * 60))

MESES = {
    "gener": 1, "febrer": 2, "març": 3, "abril": 4, "maig": 5, "juny": 6,
    "juliol": 7, "agost": 8, "setembre": 9, "octubre": 10, "novembre": 11, "desembre": 12
}

# "27 d'octubre de 2026", "2 de novembre de 2026", "27 d'octubre 2026"
REGEX_FECHA = re.compile(r"(\d{1,2})\s+(?:de\s+|d['’]\s*)([a-zç]+)\s+(?:de\s+)?(\d{4})")
REGEX_MES_ANO = re.compile(r"([a-zç]+)\s+(?:de\s+)?(\d{4})")
REGEX_DATA_URL = re.compile(r"[?&]data=(\d{8})")
TIPOS_IMPORTANTES = ("Document", "XHR", "Fetch")


# ---------------------------------------------------------------------------
# Monitor de red: lee el log de rendimiento de Chrome (eventos Network.*)
# para saber qué peticiones HTTP hay abiertas y con qué código respondieron.
# ---------------------------------------------------------------------------
class MonitorRed:
    def __init__(self, driver):
        self.driver = driver
        self.pendientes = {}   # requestId -> (método, url, tipo)
        self.respuestas = []   # (método, url, status, tipo) desde la última marca

    def _leer(self):
        try:
            entradas = self.driver.get_log("performance")
        except Exception:
            return
        for entrada in entradas:
            try:
                msg = json.loads(entrada["message"])["message"]
            except Exception:
                continue
            metodo, p = msg.get("method"), msg.get("params", {})
            rid = p.get("requestId")
            if metodo == "Network.requestWillBeSent":
                url = p["request"]["url"]
                if not url.startswith(("data:", "blob:")):
                    self.pendientes[rid] = (p["request"]["method"], url, p.get("type", "Other"))
            elif metodo == "Network.responseReceived":
                metodo_http, url, tipo = self.pendientes.get(rid, ("?", p["response"]["url"], p.get("type", "Other")))
                self.respuestas.append((metodo_http, url, int(p["response"]["status"]), tipo))
            elif metodo in ("Network.loadingFinished", "Network.loadingFailed"):
                info = self.pendientes.pop(rid, None)
                if metodo == "Network.loadingFailed" and info and not p.get("canceled"):
                    self.respuestas.append((info[0], info[1], 0, info[2]))  # 0 = fallo de red

    def marcar(self):
        """Descarta lo anterior; las respuestas posteriores pertenecen a la próxima acción."""
        self._leer()
        self.pendientes.clear()
        self.respuestas = []

    def hay_actividad(self):
        self._leer()
        return bool(self.pendientes or self.respuestas)

    def esperar(self, requiere_respuesta=False, timeout=TIMEOUT_RED):
        """Espera a que no queden peticiones abiertas. Devuelve las respuestas recibidas."""
        inicio = time.time()
        sin_pendientes_desde = None
        while time.time() - inicio < timeout:
            self._leer()
            listo = not self.pendientes and (self.respuestas or not requiere_respuesta)
            if listo:
                sin_pendientes_desde = sin_pendientes_desde or time.time()
                if time.time() - sin_pendientes_desde >= QUIETUD_RED:
                    return list(self.respuestas)
            else:
                sin_pendientes_desde = None
            time.sleep(0.1)
        if self.pendientes:
            print(f"  Aviso: {len(self.pendientes)} petición(es) sin terminar tras {timeout}s.")
        return list(self.respuestas)

    @staticmethod
    def errores(respuestas):
        """Solo cuentan páginas y llamadas AJAX; un 404 de una imagen o del favicon no importa."""
        return [r for r in respuestas
                if r[3] in TIPOS_IMPORTANTES and (r[2] == 0 or r[2] >= 400)]


def accion(monitor, funcion, descripcion, requiere_respuesta=False):
    """Ejecuta una acción del navegador y espera a sus respuestas HTTP.
    Devuelve True si no hubo errores HTTP."""
    monitor.marcar()
    funcion()
    respuestas = monitor.esperar(requiere_respuesta=requiere_respuesta)
    errores = MonitorRed.errores(respuestas)
    if requiere_respuesta and not respuestas:
        print(f"  {descripcion}: sin respuesta del servidor.")
        return False
    if errores:
        for metodo, url, status, _ in errores:
            print(f"  {descripcion}: HTTP {status or 'ERROR'} en {metodo} {url.split('?')[0]}")
        return False
    if respuestas:
        print(f"  {descripcion}: OK ({len(respuestas)} respuesta(s), última HTTP {respuestas[-1][2]})")
    return True


# ---------------------------------------------------------------------------
# Reparto de horas
# ---------------------------------------------------------------------------
def valor_a_minutos(valor):
    """Las opciones de QBid tienen value en horas: "0", "0.25", "1.0", "5.0"."""
    try:
        return int(round(float(valor) * 60))
    except (TypeError, ValueError):
        return None


def opciones_duracion(select_element):
    """Devuelve {minutos: value} con las opciones del desplegable."""
    opciones = {}
    for opt in Select(select_element).options:
        valor = opt.get_attribute("value")
        minutos = valor_a_minutos(valor)
        if minutos is not None and minutos not in opciones:
            opciones[minutos] = valor
    return opciones


def repartir_minutos(campos_opciones, objetivo, inicio):
    """Reparte `objetivo` minutos entre los campos de forma equilibrada, usando solo
    valores disponibles en cada desplegable. Devuelve lista de minutos o None."""
    n = len(campos_opciones)
    orden = [(inicio + i) % n for i in range(n)]
    base, extra = divmod(objetivo // PASO_MINUTOS, n)

    asignacion = [0] * n
    for k, idx in enumerate(orden):
        asignacion[idx] = (base + (1 if k < extra else 0)) * PASO_MINUTOS
    if all(asignacion[i] in campos_opciones[i] for i in range(n)) and sum(asignacion) == objetivo:
        return asignacion

    # Alternativa: combinación exacta más equilibrada (programación dinámica)
    media = objetivo / n
    mejor = {0: (0.0, [])}
    for idx in orden:
        nuevo = {}
        for suma, (coste, valores) in mejor.items():
            for v in campos_opciones[idx]:
                s = suma + v
                if s > objetivo:
                    continue
                c = coste + (v - media) ** 2
                if s not in nuevo or c < nuevo[s][0]:
                    nuevo[s] = (c, valores + [(idx, v)])
        mejor = nuevo
    if objetivo not in mejor:
        return None
    for idx, v in mejor[objetivo][1]:
        asignacion[idx] = v
    return asignacion


# ---------------------------------------------------------------------------
# Utilidades de navegación
# ---------------------------------------------------------------------------
def entrar_frames(driver):
    """Todo el contenido vive en top > iframe jspContainer > iframe contentmain."""
    driver.switch_to.default_content()
    driver.switch_to.frame("jspContainer")
    driver.switch_to.frame("contentmain")


def esperar_condicion(condicion, timeout=TIMEOUT_RED):
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            resultado = condicion()
            if resultado:
                return resultado
        except Exception:
            pass
        time.sleep(0.2)
    return None


def es_obsoleto(elemento):
    """True cuando el frame se ha recargado y el elemento viejo ya no existe."""
    try:
        elemento.is_enabled()
        return False
    except StaleElementReferenceException:
        return True


def clic_js(driver, elemento):
    driver.execute_script("arguments[0].click();", elemento)


def leer_alerta(driver):
    """Si hay un alert() abierto, lo acepta y devuelve su texto."""
    try:
        alerta = driver.switch_to.alert
        texto = alerta.text
        alerta.accept()
        return texto
    except NoAlertPresentException:
        return None


# ---------------------------------------------------------------------------
# Login y Agenda
# ---------------------------------------------------------------------------
def buscar_password(driver):
    """Busca el campo de contraseña en la página o en sus frames (deja el foco en ese frame)."""
    driver.switch_to.default_content()
    campos = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
    if campos:
        return campos[0]
    for frame in driver.find_elements(By.CSS_SELECTOR, "iframe, frame"):
        driver.switch_to.frame(frame)
        campos = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if campos:
            return campos[0]
        driver.switch_to.default_content()
    return None


def login(driver, monitor):
    if calendario_visible(driver):
        return True  # Sesión ya iniciada
    campo_pass = esperar_condicion(lambda: buscar_password(driver), timeout=20)
    if campo_pass is None:
        print("No se encontró el formulario de login.")
        return False
    if not QBID_USER or not QBID_PASSWD:
        print(f"No hay QBID_USER/QBID_PASSWD en .env. Inicia sesión a mano (máx. {TIMEOUT_LOGIN_MANUAL}s)...")
        return True

    campo_user = campo_pass.find_element(
        By.XPATH,
        "preceding::input[(@type='text' or @type='email' or not(@type)) and not(@type='hidden')][1]",
    )
    campo_user.clear()
    campo_user.send_keys(QBID_USER)
    campo_pass.clear()
    campo_pass.send_keys(QBID_PASSWD)
    botones = campo_pass.find_elements(
        By.XPATH, "following::*[self::button or (self::input and (@type='submit' or @type='button'))][1]"
    )

    def enviar():
        if botones:
            clic_js(driver, botones[0])
        else:
            campo_pass.submit()

    ok = accion(monitor, enviar, "Login", requiere_respuesta=True)
    alerta = leer_alerta(driver)
    if alerta:
        print(f"QBid dice: {alerta}")
        return False
    if buscar_password(driver) is not None:
        print("El login no se completó (sigue apareciendo el formulario). Revisa usuario/contraseña.")
        return False
    driver.switch_to.default_content()
    return ok


def calendario_visible(driver):
    try:
        entrar_frames(driver)
        return bool(driver.find_elements(By.CSS_SELECTOR, CSS_CABECERA_MES))
    except Exception:
        return False


def ir_a_agenda(driver, monitor):
    """Tras el login QBid abre la Agenda solo. Si no, pulsa "Agenda" en el menú."""
    timeout = TIMEOUT_LOGIN_MANUAL if not (QBID_USER and QBID_PASSWD) else TIMEOUT_RED
    if esperar_condicion(lambda: calendario_visible(driver), timeout=timeout):
        return True
    try:
        driver.switch_to.default_content()
        driver.switch_to.frame("jspContainer")
        enlace = driver.find_element(By.XPATH, XPATH_MENU_AGENDA)
        accion(monitor, lambda: clic_js(driver, enlace), "Abrir Agenda")
    except Exception as e:
        print(f"No se encontró el menú Agenda: {e}")
    return bool(esperar_condicion(lambda: calendario_visible(driver)))


def mes_calendario(driver):
    entrar_frames(driver)
    texto = driver.find_element(By.CSS_SELECTOR, CSS_CABECERA_MES).text.strip().lower()
    m = REGEX_MES_ANO.search(texto)
    if not m or m.group(1) not in MESES:
        raise RuntimeError(f"Cabecera de mes no reconocida: '{texto}'")
    return date(int(m.group(2)), MESES[m.group(1)], 1)


def ir_a_mes(driver, monitor, objetivo):
    """Mueve el calendario de la Agenda al mes de `objetivo` con popupAgenda.shiftAgenda(n)."""
    actual = mes_calendario(driver)
    diferencia = (objetivo.year - actual.year) * 12 + (objetivo.month - actual.month)
    if diferencia == 0:
        return
    accion(monitor, lambda: driver.execute_script(f"popupAgenda.shiftAgenda({diferencia});"),
           f"Calendario a {objetivo.strftime('%m/%Y')}")
    destino = date(objetivo.year, objetivo.month, 1)
    if esperar_condicion(lambda: mes_calendario(driver) == destino) is None:
        raise RuntimeError(f"El calendario no llegó a {destino.strftime('%m/%Y')}.")


def abrir_dia_desde_agenda(driver, monitor, dia):
    """Selecciona `dia` en el calendario. Devuelve True si se abrió su Activitat diària."""
    ir_a_mes(driver, monitor, dia)
    entrar_frames(driver)
    celdas = driver.find_elements(By.CSS_SELECTOR, f"#monthView td#cellDay{dia.day}")
    if not celdas:
        return False
    accion(monitor, lambda: clic_js(driver, celdas[0]), f"Seleccionar {dia.strftime('%d/%m/%Y')}")
    entrar_frames(driver)
    enlaces = driver.find_elements(By.CSS_SELECTOR, CSS_ENLACE_DOSSIER)
    if not enlaces:
        tareas = driver.find_elements(By.ID, "tablaTasquesDia")
        motivo = tareas[0].text.strip() if tareas else "sin tareas"
        print(f"  {dia.strftime('%d/%m/%Y')}: sin Activitat diària ({motivo}).")
        return False
    viejo = driver.find_element(By.TAG_NAME, "html")
    if not accion(monitor, lambda: clic_js(driver, enlaces[0]), "Abrir dossier", requiere_respuesta=True):
        raise RuntimeError("Error HTTP al abrir el dossier.")
    esperar_condicion(lambda: es_obsoleto(viejo))
    if esperar_condicion(lambda: fecha_actividad(driver) is not None) is None:
        raise RuntimeError("No cargó la página de Activitat diària.")
    return True


def entrar_primer_dia(driver, monitor):
    """Abre la Activitat diària de FECHA_INICIO, o del siguiente día que la tenga."""
    dia = fecha_inicio
    for _ in range(MAX_DIAS_SIN_TAREA):
        if dia > fecha_final:
            return False
        if abrir_dia_desde_agenda(driver, monitor, dia):
            return True
        dia += timedelta(days=1)
    raise RuntimeError(f"Ningún día con Activitat diària entre {fecha_inicio} y {dia}.")


# ---------------------------------------------------------------------------
# Página de Activitat diària
# ---------------------------------------------------------------------------
def fecha_actividad(driver):
    """Fecha del día abierto: primero el parámetro data=YYYYMMDD de la URL del frame,
    si no, el texto de la cabecera ("Dimarts, 27 d'octubre de 2026")."""
    entrar_frames(driver)
    url = driver.execute_script("return window.location.href;") or ""
    m = REGEX_DATA_URL.search(url)
    if m and "ActivitatFct" in url:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    for e in driver.find_elements(By.XPATH, "//div[contains(@class,'panel-heading')]/label"):
        m = REGEX_FECHA.search(e.text.lower())
        if m and m.group(2) in MESES:
            return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
    return None


def horas_maximas(driver):
    """Lee "Hores màximes: 5H" de la página (None si no aparece)."""
    texto = driver.find_element(By.TAG_NAME, "body").text
    m = re.search(r"Hores m[àa]ximes:?\s*(\d+(?:[.,]\d+)?)\s*H", texto, re.IGNORECASE)
    return float(m.group(1).replace(",", ".")) if m else None


def minutos_registrados(driver):
    """Suma de las horas seleccionadas ahora mismo en la página (en minutos)."""
    entrar_frames(driver)
    return sum(valor_a_minutos(Select(s).first_selected_option.get_attribute("value")) or 0
               for s in driver.find_elements(By.CSS_SELECTOR, CSS_SELECTS_HORAS))


def rellenar_dia(driver, monitor, posicion_inicial):
    """Rellena los desplegables. Devuelve (nueva_posición, estado) con estado en
    "guardar", "ya_hecho", "futuro", "vacio" o "error"."""
    todos = driver.find_elements(By.CSS_SELECTOR, CSS_SELECTS_HORAS)
    campos = [(s, opciones_duracion(s)) for s in todos if s.is_enabled()]

    if todos and not campos:
        print("Los campos están bloqueados (día futuro).")
        return posicion_inicial, "futuro"
    if not campos:
        print("No hay campos de horas en este día (festivo o ausencia); se salta.")
        return posicion_inicial, "vacio"

    maximo = horas_maximas(driver)
    if maximo is not None and HORAS_A_RELLENAR > maximo:
        print(f"ERROR: HORAS_A_RELLENAR={HORAS_A_RELLENAR} supera las Hores màximes de QBid ({maximo}H).")
        return posicion_inicial, "error"

    actual = sum(valor_a_minutos(Select(s).first_selected_option.get_attribute("value")) or 0 for s, _ in campos)
    if actual == MINUTOS_OBJETIVO:
        print(f"Ya tiene {HORAS_A_RELLENAR}h registradas; no se toca.")
        return posicion_inicial, "ya_hecho"
    if actual:
        print(f"Tenía {actual // 60}h {actual % 60:02d}min; se corrige a {HORAS_A_RELLENAR}h.")

    n = len(campos)
    posicion_inicial %= n
    asignacion = repartir_minutos([o for _, o in campos], MINUTOS_OBJETIVO, posicion_inicial)
    if asignacion is None:
        print(f"ERROR: no es posible sumar exactamente {HORAS_A_RELLENAR}h con {n} campos.")
        return posicion_inicial, "error"

    for (select_element, opciones), minutos in zip(campos, asignacion):
        Select(select_element).select_by_value(opciones[minutos])
    # QBid recalcula "Hores introduïdes" con updateHoresConsignades()
    driver.execute_script("if (typeof updateHoresConsignades === 'function') updateHoresConsignades();")

    total = sum(valor_a_minutos(Select(s).first_selected_option.get_attribute("value")) or 0 for s, _ in campos)
    if total != MINUTOS_OBJETIVO:
        print(f"ERROR: la suma seleccionada es {total} min (esperado {MINUTOS_OBJETIVO}).")
        return posicion_inicial, "error"

    print(f"Reparto en {n} campos: " + ", ".join(f"{m}min" for m in asignacion))
    return (posicion_inicial + 1) % n, "guardar"


def guardar_dia(driver, monitor):
    """Pulsa "Emmagatzemar" y comprueba que el POST responde bien.
    El clic se lanza con setTimeout para que un alert() de QBid no bloquee Selenium."""
    boton = driver.find_element(By.CSS_SELECTOR, CSS_BOTON_GUARDAR)
    viejo = driver.find_element(By.TAG_NAME, "html")
    monitor.marcar()
    driver.execute_script("var b = arguments[0]; setTimeout(function () { b.click(); }, 0);", boton)

    # O sale un alert (QBid rechaza las horas) o empieza el POST
    inicio = time.time()
    while time.time() - inicio < TIMEOUT_RED:
        try:
            alerta = leer_alerta(driver)
        except UnexpectedAlertPresentException:
            alerta = leer_alerta(driver)
        if alerta:
            raise RuntimeError(f"QBid rechazó el guardado: {alerta}")
        if monitor.hay_actividad():
            break
        time.sleep(0.1)

    respuestas = monitor.esperar(requiere_respuesta=True)
    errores = MonitorRed.errores(respuestas)
    posts = [r for r in respuestas if r[0] == "POST" and "ActivitatFct" in r[1]]
    if errores:
        raise RuntimeError("Error HTTP al guardar: " + ", ".join(f"{s} {u.split('?')[0]}" for _, u, s, _ in errores))
    if not posts:
        raise RuntimeError("No se detectó el envío (POST) del formulario.")
    print(f"  Guardar: OK (POST HTTP {posts[-1][2]})")
    esperar_condicion(lambda: es_obsoleto(viejo))
    esperar_condicion(lambda: fecha_actividad(driver) is not None)


def ir_al_dia_siguiente(driver, monitor, fecha_anterior):
    entrar_frames(driver)
    flechas = driver.find_elements(By.XPATH, XPATH_FLECHA_SIGUIENTE)
    if not flechas:
        raise RuntimeError("No se encontró la flecha 'Següent'.")
    viejo = driver.find_element(By.TAG_NAME, "html")
    if not accion(monitor, lambda: clic_js(driver, flechas[0]), "Día siguiente", requiere_respuesta=True):
        raise RuntimeError("Error HTTP al pasar al día siguiente.")
    esperar_condicion(lambda: es_obsoleto(viejo))
    nueva = esperar_condicion(lambda: (fecha_actividad(driver) or fecha_anterior) > fecha_anterior
                              and fecha_actividad(driver))
    if not nueva:
        raise RuntimeError("La fecha no cambió tras pulsar 'Següent'.")
    return nueva


# ---------------------------------------------------------------------------
# Diagnóstico y estado
# ---------------------------------------------------------------------------
def volcar_debug(driver, motivo):
    """Guarda captura y HTML de la página y de cada frame en debug/ para poder ajustar selectores."""
    carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug",
                           datetime.now().strftime("%Y%m%d_%H%M%S"))
    try:
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, "motivo.txt"), "w", encoding="utf-8") as f:
            f.write(f"{motivo}\nURL: {driver.current_url}\n")
        driver.switch_to.default_content()
        driver.save_screenshot(os.path.join(carpeta, "captura.png"))

        def volcar(ruta):
            nombre = "pagina" + "".join(f"_frame{i}" for i in ruta)
            with open(os.path.join(carpeta, nombre + ".html"), "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            if len(ruta) >= 3:
                return
            for i in range(len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))):
                driver.switch_to.default_content()
                for j in ruta:
                    driver.switch_to.frame(j)
                driver.switch_to.frame(i)
                volcar(ruta + [i])

        volcar([])
        driver.switch_to.default_content()
        print(f"Diagnóstico guardado en {carpeta} (envíalo para ajustar el script).")
    except Exception as e:
        print(f"No se pudo guardar el diagnóstico: {e}")


def guardar_fecha_inicio(nueva_fecha):
    """Reescribe FECHA_INICIO_STR en este mismo archivo."""
    ruta = os.path.abspath(__file__)
    with open(ruta, encoding="utf-8") as f:
        codigo = f.read()
    nuevo, cambios = re.subn(
        r'^FECHA_INICIO_STR\s*=\s*"[^"]*"',
        f'FECHA_INICIO_STR = "{nueva_fecha.strftime("%d/%m/%Y")}"',
        codigo, count=1, flags=re.MULTILINE,
    )
    if cambios:
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(nuevo)
        os.replace(tmp, ruta)
        print(f"FECHA_INICIO_STR actualizada a {nueva_fecha.strftime('%d/%m/%Y')}.")


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Iniciando QBid Automator: {HORAS_A_RELLENAR}h por día")
    print(f"Rango: {fecha_inicio.strftime('%d/%m/%Y')} -> {fecha_final.strftime('%d/%m/%Y')} (hoy)")

    if fecha_inicio > fecha_final:
        print("La fecha de inicio es posterior a hoy; no hay nada que rellenar.")
        sys.exit(0)

    opciones_chrome = webdriver.ChromeOptions()
    opciones_chrome.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    # Si salta un alert inesperado, que Selenium no lo cierre solo: lo leemos nosotros
    opciones_chrome.set_capability("unhandledPromptBehavior", "ignore")
    # Selenium Manager busca Chrome y su driver; si Chrome no está instalado, descarga uno
    driver = webdriver.Chrome(service=Service(), options=opciones_chrome)
    monitor = MonitorRed(driver)
    ultimo_dia_registrado = None

    try:
        if not accion(monitor, lambda: driver.get(URL_LOGIN), "Cargar QBid", requiere_respuesta=True):
            raise RuntimeError("No se pudo cargar la página de QBid.")
        if not login(driver, monitor):
            raise RuntimeError("Login fallido.")
        if not ir_a_agenda(driver, monitor):
            raise RuntimeError("No se encontró el calendario de la Agenda.")

        if entrar_primer_dia(driver, monitor):
            posicion_inicial = 0
            fecha_actual = fecha_actividad(driver)

            while True:
                print(f"\n--- {fecha_actual.strftime('%d/%m/%Y')} ---")
                if fecha_actual > fecha_final:
                    print("Se ha llegado al día de hoy.")
                    break

                posicion_inicial, estado = rellenar_dia(driver, monitor, posicion_inicial)
                if estado == "futuro":
                    break
                if estado == "error":
                    raise RuntimeError(f"No se pudo rellenar el {fecha_actual.strftime('%d/%m/%Y')}.")
                if estado == "guardar":
                    guardar_dia(driver, monitor)
                    # Tras guardar, la página se recarga: confirma que quedó el total correcto
                    if fecha_actividad(driver) == fecha_actual:
                        registrado = minutos_registrados(driver)
                        if registrado != MINUTOS_OBJETIVO:
                            raise RuntimeError(f"Tras guardar, QBid muestra {registrado} min "
                                               f"(esperado {MINUTOS_OBJETIVO}).")
                        print(f"  Comprobado: QBid muestra {HORAS_A_RELLENAR}h guardadas.")
                if estado in ("guardar", "ya_hecho"):
                    ultimo_dia_registrado = fecha_actual

                if fecha_actual >= fecha_final:
                    print("Día de hoy procesado.")
                    break
                if fecha_actividad(driver) == fecha_actual:
                    fecha_actual = ir_al_dia_siguiente(driver, monitor, fecha_actual)
                else:
                    # Tras guardar QBid no volvió al mismo día: seguir desde la Agenda
                    print("  QBid no volvió al día guardado; se continúa desde la Agenda.")
                    if not ir_a_agenda(driver, monitor):
                        raise RuntimeError("No se pudo volver a la Agenda.")
                    dia = fecha_actual + timedelta(days=1)
                    for _ in range(MAX_DIAS_SIN_TAREA):
                        if dia > fecha_final or abrir_dia_desde_agenda(driver, monitor, dia):
                            break
                        dia += timedelta(days=1)
                    if dia > fecha_final:
                        print("Se ha llegado al día de hoy.")
                        break
                    fecha_actual = fecha_actividad(driver)
                    if fecha_actual is None:
                        raise RuntimeError("No se pudo abrir el siguiente día desde la Agenda.")
        else:
            print("No hay días pendientes hasta hoy.")

        print("\n========================================================")
        print("Automatización finalizada.")

    except Exception as main_error:
        print(f"Error crítico: {main_error}")
        volcar_debug(driver, str(main_error))

    finally:
        if ultimo_dia_registrado:
            guardar_fecha_inicio(ultimo_dia_registrado)
        else:
            print("No se registró ningún día; FECHA_INICIO_STR no cambia.")
        driver.quit()
        print("Programa cerrado.")
