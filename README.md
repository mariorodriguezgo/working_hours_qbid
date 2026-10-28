# working_hours_qbid

Script de Python que rellena automáticamente las horas de la **"Activitat diària del dossier"** en [qBID](https://www.empresaiformacio.org/sBid), la plataforma de prácticas FCT/Dual de Catalunya.

Inicia sesión, recorre los días desde la última fecha registrada hasta hoy y reparte las horas del día entre las actividades del plan, sin tener que tocar nada.

## Qué hace

- **Total exacto cada día:** reparte las horas (por defecto 5h) entre todos los campos del día, sean cuantos sean. Comprueba la suma antes y después de guardar.
- **Reparto rotativo:** los campos con más tiempo cambian cada día, para que el reparto no sea siempre igual.
- **Sin intervención:** inicia sesión con tus credenciales del `.env` y navega solo por la Agenda.
- **Espera a la web, no al reloj:** cada paso espera a las respuestas HTTP de qBID en lugar de usar pausas fijas. Si hay un error HTTP o qBID muestra un aviso, se detiene.
- **Respeta lo que ya está hecho:**
  - deja como están los días que ya tienen las horas completas;
  - corrige los que tienen menos;
  - salta festivos y fines de semana;
  - se para en los días futuros.
- **Recuerda dónde se quedó:** al terminar, guarda el último día registrado en `FECHA_INICIO_STR`, así la siguiente ejecución sigue desde ahí. La fecha final es siempre hoy.

## Requisitos

- Python 3.10 o superior
- Google Chrome (si no está instalado, Selenium descarga uno automáticamente)
- Una cuenta de alumno en qBID

## Instalación

```bash
git clone https://github.com/mariorodriguezgo/working_hours_qbid.git
cd working_hours_qbid
python -m venv venv
```

Activa el entorno virtual:

```bash
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Linux / macOS
source venv/bin/activate
```

Instala las dependencias:

```bash
pip install -r requirements.txt
```

> En Windows, si `Activate.ps1` da un error de permisos, ejecuta antes `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Configuración

1. Copia el archivo de ejemplo y pon tus credenciales de qBID:

   ```bash
   cp .env.example .env        # Windows: copy .env.example .env
   ```

   ```ini
   QBID_USER=tu_usuario
   QBID_PASSWD=tu_contraseña
   ```

   El `.env` está en `.gitignore` y nunca se sube al repositorio.

2. Ajusta las constantes al principio de `fill_hours_qbid.py`:

   | Constante | Qué es |
   |---|---|
   | `HORAS_A_RELLENAR` | Horas por día. No puede superar las "Hores màximes" de tu conveni. |
   | `FECHA_INICIO_STR` | Primer día a rellenar (`DD/MM/AAAA`). Se actualiza sola tras cada ejecución. |

## Uso

```bash
python fill_hours_qbid.py
```

Se abre Chrome, el script inicia sesión y va día a día mostrando en la terminal el reparto de cada día y el resultado de cada guardado. Al acabar, Chrome se cierra solo.

**Consejo:** la primera vez, pon en `FECHA_INICIO_STR` un día reciente y comprueba en qBID que ha quedado bien antes de rellenar un rango largo.

### Ejemplo de salida

```
Iniciando QBid Automator: 5h por día
Rango: 26/10/2026 -> 28/10/2026 (hoy)

--- 26/10/2026 ---
Tenía 4h 30min; se corrige a 5h.
Reparto en 15 campos: 15min, 15min, 30min, 30min, 30min, 30min, 30min, 15min, ...
  Guardar: OK (POST HTTP 200)
  Comprobado: QBid muestra 5h guardadas.
...
Automatización finalizada.
FECHA_INICIO_STR actualizada a 28/10/2026.
```

## Si algo falla

El script se detiene y guarda en `debug/<fecha_hora>/`:

- `motivo.txt`: qué falló y en qué URL;
- `captura.png`: captura de pantalla;
- `pagina*.html`: el HTML de la página y de cada frame.

Con esos archivos se pueden ajustar los selectores si qBID cambia su web. La carpeta `debug/` contiene datos personales y no se sube a git.

| Error | Solución |
|---|---|
| `cannot find Chrome binary` | Actualiza el repo (`git pull`) o instala Chrome. |
| `Login fallido` | Revisa usuario y contraseña en `.env`. |
| `supera las Hores màximes` | Baja `HORAS_A_RELLENAR` al máximo de tu conveni. |
| `QBid rechazó el guardado: ...` | El texto es el aviso de qBID; normalmente horas de más o de menos. |

## Cómo funciona

- Toda la web de qBID vive en dos iframes anidados: `jspContainer` → `contentmain`.
- El script lee el log de red de Chrome (eventos `Network.*`) para saber cuándo ha terminado cada petición y con qué código HTTP.
- La estructura de las páginas (selectores, funciones JS, peticiones) está documentada en [`docs/qbid_estructura.md`](docs/qbid_estructura.md).

## Aviso

Proyecto personal sin relación con qBID ni con el Departament d'Educació. Úsalo bajo tu responsabilidad: las horas que registra deben corresponder a la actividad que has hecho de verdad, y es tu responsabilidad revisarlas. Si qBID cambia su web, puede que haya que actualizar los selectores.
