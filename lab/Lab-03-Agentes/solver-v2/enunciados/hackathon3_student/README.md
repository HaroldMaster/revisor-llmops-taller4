# Hackathon 3 · Una neurona aprende AND

El documento principal es **Hackathon_3_Starter.ipynb**. El enunciado PDF resume
las condiciones y los criterios; no reemplaza las explicaciones del notebook.

## Preparar el entorno antes de la clase

Descomprime el paquete completo. No abras el notebook dentro del ZIP.
Con `uv` disponible, abre una terminal en `hackathon3_student` y ejecuta:

```bash
uv sync --locked
uv run jupyter lab
```

El proyecto selecciona Python 3.13 y crea su propio `.venv`. La primera
instalación requiere conexión para descargar lo que falte. Después, el
hackathon no requiere red, datos externos, PyTorch ni GPU.

En Jupyter abre `Hackathon_3_Starter.ipynb`. Si hay varios kernels, selecciona
el Python del entorno que acaba de crear este proyecto. No uses un Jupyter
abierto desde otro entorno. No es necesario instalar extensiones.

## Durante la actividad

1. Escribe los nombres de ambos integrantes.
2. Lee las etapas en orden y escribe cada predicción antes de ejecutar.
3. Completa solo `predecir`, `actualizar` y `paso_entrenamiento`, además de las
   respuestas escritas. El ejemplo inicial está resuelto.
4. Los mensajes `PENDIENTE` indican una actividad aún no completada. No son una
   calificación ni ocultan una solución que se ejecute automáticamente.
5. Si modificas una función, vuelve a ejecutarla y luego sus comprobaciones.
   Para reconstruir un estado consistente, reinicia el kernel y ejecuta todo.
6. No modifiques `and_lab.py`, `verify_notebook.py`, `contrato.json` ni las
   celdas proporcionadas. No elimines ni reordenes celdas.

El motor educativo se proporciona completo. No tienes que leer su código para
resolver las tareas. Las ayudas desplegables están permitidas.

## Verificar y entregar

Guarda el notebook. Desde esta misma carpeta ejecuta:

```bash
uv run python verify_notebook.py
```

El verificador primero detecta tareas o respuestas pendientes. Solo si la
estructura está completa ejecuta una copia desde cero, usando el mismo
intérprete con el que fue iniciado. No cambia el notebook original.

El resultado satisfactorio dice `VERIFICACIÓN TÉCNICA COMPLETA` y produce:

- `output/verificacion/Hackathon_3_Verificado.ipynb`;
- `output/verificacion/traza_entrenamiento.csv`;
- `output/verificacion/tabla_and.csv`;
- `output/verificacion/entrenamiento_and.png`;
- `output/verificacion/verificacion.json` con fecha y hashes de esa ejecución.

El verificador comprueba presencia de respuestas, no su comprensión ni que las
predicciones se escribieron a tiempo. Esa revisión corresponde al docente.

Entrega un ZIP con **Hackathon_3_Starter.ipynb** guardado y **output/**. No
incluyas `.venv/`, cachés ni materiales docentes. Si queda trabajo pendiente,
conserva lo realizado y entrega la evidencia parcial; no fabriques resultados.

## Si algo no funciona

- **No encuentra `and_lab`:** abre el notebook dentro de la carpeta completa
  del paquete, no una copia aislada del archivo.
- **Falta una biblioteca:** vuelve a `uv sync --locked` antes de clase y usa
  `uv run jupyter lab` desde esta carpeta.
- **Grafo ya recorrido:** vuelve a ejecutar la celda de preparación del ejemplo;
  un forward nuevo crea el grafo para el siguiente backward.
- **Comprobación numérica fallida:** lee el mensaje y revisa la función
  correspondiente. Las pruebas no exigen que reconstruyas el motor.
- **El verificador dice que una celda proporcionada cambió:** conserva tus
  respuestas, recupera esa celda del ZIP original y vuelve a guardar.
