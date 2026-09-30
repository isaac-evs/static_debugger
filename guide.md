# Guía rápida: cómo usar AbinDebugger

Esta guía explica cómo usar la aplicación paso a paso, sin necesidad de
saber programar.

## 1. Abrir la aplicación

**En Mac:** haz doble clic en `AbinDebugger.app`.

La primera vez, macOS mostrará un aviso diciendo que no puede verificar
quién hizo la aplicación. Esto es normal (no está firmada digitalmente).
Para abrirla:
1. Haz clic derecho (o Ctrl+clic) sobre `AbinDebugger.app`.
2. Elige **Abrir**.
3. Vuelve a hacer clic en **Abrir** en el cuadro que aparece.

Solo necesitas hacer esto la primera vez.

**En Windows:** entra a la carpeta `AbinDebugger` y haz doble clic en
`AbinDebugger.exe`.

Windows también mostrará un aviso de seguridad la primera vez ("Windows
protegió su PC"). Haz clic en **Más información** y luego en **Ejecutar
de todas formas**.

Se abrirá una ventana con el programa. No necesitas instalar nada más.

## 2. Elegir qué revisar

En la ventana verás tres listas desplegables:

1. **Model** — el archivo con la función que tiene el error.
2. **Tests** — el archivo con los casos de prueba (ejemplos de entradas
   y el resultado que deberían dar).
3. **Function** — el nombre de la función a revisar. Esta lista se
   llena automáticamente según el archivo elegido en "Model".

Si es tu primera vez, deja los valores que aparecen por defecto — son
un ejemplo incluido para probar.

## 3. Ejecutar

Haz clic en el botón **Run debugger**.

Del lado derecho aparecerá el progreso en vivo, como una consola de
texto: qué se está probando, qué líneas parecen sospechosas, y qué
cambios se están intentando.

Al terminar, verás uno de estos tres resultados:

- **SUCCESSFUL REPAIR** — encontró un arreglo. Se muestra el código
  corregido.
- **NO DEFECT FOUND** — el código ya pasaba todas las pruebas, no había
  nada que arreglar.
- **UNABLE TO REPAIR** — no logró encontrar un arreglo con los intentos
  disponibles.

Ninguno de estos resultados es un error del programa — son,
simplemente, lo que encontró.

## 4. Generar casos de prueba con IA (opcional)

Si no tienes un archivo de pruebas, la aplicación puede crear uno por
ti usando inteligencia artificial (Claude, ChatGPT o Gemini).

1. Junto a "AI-generated test cases", escribe cuántos casos quieres
   (por ejemplo, `5`).
2. Haz clic en **Configure…**.
3. Elige el proveedor (Claude, ChatGPT o Gemini).
4. Pega tu llave de API en el campo correspondiente (se usa solo para
   esa ejecución; nunca se guarda ni se comparte).
5. Haz clic en **Save**.
6. Haz clic en **Run debugger** como de costumbre.

Si no tienes una llave de API a mano, deja el número en `0` y usa la
aplicación sin esta función — el resto funciona igual.

## 5. Ver y descargar los resultados

Cuando la ejecución termina, aparece un panel de **Results** con:

- El estado final (reparado, sin defectos, o no reparado).
- Cuántas pruebas pasaban antes y cuántas pasan después.
- Cuántos intentos hizo y cuánto tiempo tardó.

Haz clic en **Download results (CSV)** para guardar una tabla con el
detalle de cada prueba (antes/después) en tu computadora.

## 6. Copiar la salida

Si quieres copiar todo el texto de la consola (por ejemplo, para
compartirlo), haz clic en el botón **Copy** que está arriba del panel
de salida en vivo.

## ¿Algo no funciona?

- Si el programa no encuentra una función, revisa que elegiste el
  archivo correcto en "Model" antes de elegir la función.
- Si la generación con IA falla, revisa que la llave de API sea
  correcta y tenga crédito disponible con ese proveedor.
- Cualquier otro error se muestra directamente en el panel de salida en
  vivo, en rojo.
