# Dockerfile

# 1. Usar la imagen oficial de Microsoft para Playwright con Python.
# Esto es CRUCIAL porque ya incluye los navegadores y todas las dependencias del sistema.
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# 2. Establecer el directorio de trabajo dentro del contenedor.
WORKDIR /app

# 3. Copiar el archivo de dependencias primero para aprovechar el caché de Docker.
COPY requirements.txt .

# 4. Instalar las dependencias de Python.
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiar todo el código de tu proyecto al directorio de trabajo.
COPY . .

# 6. Exponer el puerto en el que correrá Gunicorn.
EXPOSE 8000

# 7. El comando para ejecutar la aplicación en producción.
#    - Le dice a Gunicorn que busque el objeto 'app' en el archivo 'run_app.py'.
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:8000", "run_app:app"]