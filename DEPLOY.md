# Poner la app en internet

La app necesita **Chromium** para imprimir los filings a PDF, así que
tiene que desplegarse como contenedor Docker. El `Dockerfile` de este
repo ya lo instala todo; tú no necesitas Docker en tu Mac.

---

## Opción recomendada — Render (gratis, sin tarjeta)

### 1. Subir el código a GitHub

```bash
git init
git add .
git commit -m "SEC Research Terminal"
```

Crea un repositorio vacío en https://github.com/new (por ejemplo
`sec-research-terminal`, privado) y luego:

```bash
git remote add origin https://github.com/TU-USUARIO/sec-research-terminal.git
git branch -M main
git push -u origin main
```

### 2. Desplegar

1. Entra en https://render.com y regístrate con GitHub.
2. **New → Web Service** y elige el repositorio.
3. Render detecta el `Dockerfile` solo. Plan: **Free**.
4. En **Environment**, añade la variable:

   | Clave             | Valor                                      |
   |-------------------|--------------------------------------------|
   | `SEC_USER_AGENT`  | `Tu Nombre tu-email@ejemplo.com`            |

   La SEC **exige** un contacto real ahí; sin él puede bloquear las
   peticiones del servidor.
5. **Create Web Service**. El primer build tarda unos 5 minutos.

Quedará en `https://sec-research-terminal.onrender.com` — accesible
desde el móvil o cualquier ordenador, con tu Mac apagado.

### Actualizar la web más adelante

```bash
git add .
git commit -m "cambios"
git push
```

Render vuelve a desplegar solo.

---

## Qué esperar del plan gratuito

- **Se duerme** tras 15 minutos sin visitas: la primera carga después
  tarda ~1 minuto. Las siguientes son instantáneas.
- **512 MB de RAM.** Suficiente para buscar y para la mayoría de PDFs,
  pero un 10-K muy pesado o 20 documentos a la vez puede quedarse sin
  memoria (la descarga falla y el servicio se reinicia). Si te pasa,
  descarga en tandas más pequeñas o sube de plan.
- La URL es **pública**: cualquiera con el enlace puede usarla.

## Si te quedas corto de memoria — Fly.io (~5 €/mes, 1 GB)

```bash
brew install flyctl
fly auth signup
fly launch --dockerfile Dockerfile --no-deploy
fly secrets set SEC_USER_AGENT="Tu Nombre tu-email@ejemplo.com"
fly scale memory 1024
fly deploy
```

Fly apaga la máquina cuando nadie la usa y la enciende al recibir una
visita, así que solo pagas por el tiempo en marcha.

---

## Variables de entorno

| Variable          | Para qué sirve                                      |
|-------------------|-----------------------------------------------------|
| `SEC_USER_AGENT`  | Contacto que se envía a la SEC. **Ponlo siempre.**  |
| `CHROME_PATH`     | Ruta de Chromium. El Dockerfile ya la define.       |
| `PORT`            | Puerto. Render y Fly lo inyectan solos.             |

## Ejecutar en local (como hasta ahora)

```bash
python3 app.py
```
