---
name: app-creation
description: Guía a cualquier persona de Wild Lama para crear una aplicación interna siguiendo los estándares del wl-app-kit. Úsalo cuando alguien quiera construir una app, herramienta, dashboard, calculadora, tracker, automatización o cualquier cosa parecida. Triggers: "quiero crear una aplicación", "quiero construir una herramienta", "activa la skill app-creation", "quiero hacer una app para el equipo", "necesito automatizar algo", "quiero desarrollar algo", "cómo empiezo a hacer una app en Wild Lama", "ayudame a armar algo para…", "necesito calcular / generar reportes / mostrar data de…". También activar si el usuario describe un problema operativo y menciona querer resolverlo con código, una app o una automatización.
---

# Wild Lama — Skill de Creación de Aplicaciones Internas

Esta skill acompaña a cualquier persona de Wild Lama que quiera desarrollar una herramienta interna. No asume conocimientos técnicos.

Su trabajo: guiar el proceso completo desde la idea hasta que el proyecto esté listo para revisión de Tech — asegurando que se aplican las reglas del **wl-app-kit** en cada paso.

---

## Contexto importante antes de empezar

Si el proyecto se está construyendo en **Claude Code** o **Cowork con la carpeta del proyecto abierta**, el wl-app-kit se carga automáticamente y aplica las reglas técnicas sin que el usuario haga nada.

Esta skill complementa ese proceso: hace las preguntas, guía las decisiones y lleva al usuario de punto a punto. No reemplaza al wl-app-kit — lo orquesta.

---

## Modo libre (para usuarios con experiencia)

Si el usuario ya maneja lo básico y dice algo como "sé lo que hago, quiero saltarme la guía", ofrecer **modo libre**: Claude omite las explicaciones paso a paso pero mantiene obligatorios el **Paso Cero** y la **Clasificación de tier**. Esos dos puntos no se saltan en ningún caso.

---

## FASE 1 — Validación previa (Paso Cero)

Esta fase existe porque la mejor app es la que no se construye. Es obligatoria siempre.

Hacer las siguientes preguntas en orden, una a la vez, esperando respuesta antes de continuar.

---

**Pregunta 1:**
> "¿Qué problema concreto querés resolver? Describímelo como si me lo estuvieras explicando a alguien que no conoce tu área — no el tipo de app que querés, sino el problema de negocio."

*(No aceptar respuestas como "quiero un dashboard" o "quiero una app". Pedir que describa la situación real, por ejemplo: "tardo 2 horas cada lunes consolidando datos de promotores desde tres Sheets distintas".)*

---

**Pregunta 2:**
> "¿Cómo estás resolviendo esto hoy, aunque sea de forma manual o imperfecta?"

*(Si no hay proceso actual, es posible que el problema no sea crítico. Registrar la respuesta para la evaluación.)*

---

**Pregunta 3:**
> "Dame tres razones por las que NO deberías construir esta app."

*(Esta pregunta es obligatoria. No avanzar hasta tener las tres razones. Si el usuario se traba, ofrecer posibles objeciones basadas en lo que describió — pero que él las confirme o corrija.)*

---

### Evaluación del Paso Cero

Después de las tres respuestas, evaluar si alguna de las siguientes alternativas resuelve el problema **sin necesidad de construir nada**. Proponer al menos tres opciones relevantes según el caso:

| Tipo de problema | Alternativas a evaluar |
|---|---|
| Visualizar data que se actualiza | Live Artifact en Cowork (con MCP conectado), Google Sheets con gráfico, dashboard nativo de Notion |
| Recolectar información | Google Forms + Sheets, planilla compartida |
| Automatizar entre herramientas | App Script (ecosistema Google), conector MCP directo, Zapier / Make |
| Cálculos interactivos | Sheets con fórmulas, Artifact estático en Cowork |
| Proceso que ya existe en sistemas corporativos | Funcionalidad nativa de Shopify, SAP u otras plataformas |

Para cada alternativa relevante: evaluar con el usuario si sirve antes de descartarla.

**Si una alternativa resuelve el problema:** decirlo directamente y ofrecer ayuda para implementarla. No continuar con el desarrollo de una app.

**Si ninguna alternativa alcanza:** producir el siguiente resumen y pedir confirmación antes de avanzar:

```
Resumen del Paso Cero:
- Problema: [descripción breve]
- Proceso actual: [qué hace hoy el usuario]
- Razones para NO construir: [las 3 que dio el usuario]
- Alternativas evaluadas y descartadas: [lista con motivo]
- Justificación para construir: [por qué ninguna alternativa alcanzó]

¿Confirmás que querés avanzar a construir? (sí / no / revisar)
```

Si confirma → pasar a Fase 2.
Si dice "revisar" → volver a la pregunta correspondiente.
Si dice "no" → cerrar el flujo y ofrecer ayuda con la alternativa que eligió.

---

## FASE 2 — Guía de desarrollo

Esta fase tiene 5 pasos. Ir de a uno. No avanzar al siguiente hasta que el anterior esté confirmado.

---

### Paso 1 — Clasificar la app en un tier

El tier determina qué reglas aplican, quién hace el mantenimiento después y si Tech debe intervenir antes de producción.

Hacer estas preguntas en orden. La primera condición que se cumpla define el tier:

1. ¿La app se va a comunicar con externos (clientes, proveedores, promotores, agencias)? → **Tier 3**
2. ¿La app se conecta a Shopify, SAP o GCP? → **Tier 3**
3. ¿La app procesa datos sensibles (salud, finanzas personales, datos de menores)? → **Tier 3**
4. ¿La app se conecta a herramientas internas (Google Sheets, Notion, Slack, Drive) o comparte datos entre áreas? → **Tier 2**
5. Si ninguna de las anteriores aplica → **Tier 1**

Explicar el resultado al usuario en términos simples:

> **Tier 1 — Interna simple**: uso personal o de un solo equipo, sin conexiones externas. El equipo que la construye es responsable de mantenerla.
>
> **Tier 2 — Interna con integraciones**: se conecta a herramientas internas (Sheets, Notion, Slack) o comparte datos entre áreas. Requiere registrarla en el tracker de Tech.
>
> **Tier 3 — Crítica**: conecta a sistemas corporativos, habla con externos o maneja datos sensibles. Requiere auditoría formal de Tech antes de ir a producción. Tech asume el ownership.

⚠️ Si el tier es **Tier 3**, informar al usuario en este punto:
> "Esta app requiere aprobación formal de Tech antes de conectarse a cualquier sistema productivo o comunicarse con externos. El código se puede construir, pero no puede ir a producción sin esa aprobación. El canal para iniciar la consulta es `#ai-wl`."

Producir un resumen de clasificación y pedir confirmación:

```
Clasificación propuesta: Tier [1/2/3] — [nombre]

Razón: [por qué este tier en una línea]

Implicancias:
- Documentación requerida: [lo que aplica según tier]
- Requiere auditoría de Tech antes de producción: [sí/no]
- Ownership post-lanzamiento: [equipo desarrollador / Tech]

¿Confirmás el tier, o hay algo que no encaja?
```

---

### Paso 2 — Definir qué va a hacer la app

Ayudar al usuario a escribir una descripción concreta de una sola oración:

> "Esta aplicación [hace X] para [quién], y se va a usar [con qué frecuencia]."

No avanzar con descripciones vagas. Si el usuario escribe "ayuda con las ventas", pedir que especifique qué hace exactamente, para quién y cuándo.

---

### Paso 3 — Configurar el proyecto con el wl-app-kit

Indicar al usuario que para empezar a construir necesita tener el **wl-app-kit** cargado en su agente de desarrollo.

**Si usa Cowork (Claude.ai):**
1. Descargar la carpeta del kit desde el Drive de Tech (link en `#ai-wl`).
2. Cargarla manualmente al inicio de la conversación en Cowork.
3. A partir de ahí, Claude aplica las reglas automáticamente.

**Si usa Claude Code:**
1. Descargar el kit y colocarlo en la raíz del proyecto.
2. Claude Code lo lee automáticamente al abrir la carpeta.

El kit incluye las plantillas de `.gitignore`, `.env.example` y `README.template.md` — no hace falta crearlos desde cero.

Si el usuario pregunta qué es el kit o para qué sirve:
> "El kit es un conjunto de reglas que Claude lee en segundo plano mientras trabajás. Se ocupa de que el código que se genera sea seguro, esté bien documentado y cumpla con los estándares de Wild Lama — sin que vos tengas que pensar en eso."

---

### Paso 4 — Desarrollar la app

Una vez configurado el kit, el desarrollo lo lleva el agente de IA (Claude Code o Cowork). Esta skill no reemplaza ese proceso — lo enmarca.

Recordar al usuario tres principios prácticos:

**Empezar con datos locales.** Antes de conectarse a cualquier sistema real (Sheets, Notion, Shopify, etc.), construir la app con datos de prueba inventados. Esto hace más fácil probar sin riesgo y facilita la auditoría de Tech.

**Un problema a la vez.** Construir la funcionalidad más básica primero, probarla, y luego agregar más. Las apps que intentan hacer todo desde el principio suelen quedarse a la mitad.

**Guardar el avance frecuentemente.** Cada vez que algo funcione, subir el código a GitHub. Ante cualquier duda sobre cómo hacerlo, pedirle a Claude los comandos exactos.

⚠️ **Antes de cada subida a GitHub**, usar este prompt de seguridad:
```
Antes de hacer el commit y el push, revisá todos los archivos del 
proyecto y confirmá que no hay contraseñas, API keys, tokens ni 
secrets en ningún archivo. Si encontrás algo, decime exactamente 
qué archivo y qué línea. Solo si todo está limpio, procedé con: 
git add . && git commit -m "[mensaje]" && git push
```

---

### Paso 5 — Checklist de entrega

Antes de solicitar revisión formal a Tech, verificar que se cumple todo lo siguiente.

**Checklist técnico**

| | Requisito |
|---|---|
| ☐ | El código está en un repositorio GitHub (URL disponible) |
| ☐ | El wl-app-kit está incluido en el repositorio |
| ☐ | No hay contraseñas, API keys ni tokens en ningún archivo |
| ☐ | Existe `.env.example` con las variables necesarias (sin valores reales) |
| ☐ | El archivo `.env` real está en `.gitignore` |
| ☐ | Existe `README.md` con descripción, instrucciones de uso y nombre del autor |
| ☐ | Si hay base de datos, el esquema está documentado |
| ☐ | La app funciona en modo preview con datos locales, sin conexión a sistemas productivos |

**Checklist funcional**

| | Requisito |
|---|---|
| ☐ | Está documentado qué problema resuelve la app |
| ☐ | Está documentado qué área de negocio la solicita |
| ☐ | Está registrado el tier asignado (1, 2 o 3) |
| ☐ | Se evaluaron alternativas más simples antes de construir |
| ☐ | Se completó el formulario de solicitud de revisión a Tech |

Tip para el usuario:
> "Podés pedirle a Claude que verifique el checklist técnico automáticamente: *'Revisá mi proyecto y decime cuáles puntos del checklist del wl-app-kit no están cumplidos.'*"

---

### Cierre — Cómo solicitar la revisión a Tech

Una vez completo el checklist:

> "Tu proyecto está listo para solicitar revisión formal al equipo de Tech. El siguiente paso es completar el formulario de solicitud:"
>
> 👉 https://docs.google.com/forms/d/e/1FAIpQLSfSn_uNoKcJJGjGTNhvLXqc0ZISeTzg5-DXaDJSuXyo4YAxIQ/viewform

Recordar:
- Las conversaciones informales con alguien de Tech **no cuentan** como aceptación.
- Tech responde en **3 días hábiles para apps Tier 1-2** y **5 días hábiles para Tier 3**.
- Si la respuesta tarda más de lo esperado, escribir al canal `#ai-wl`.

**Para apps Tier 2:** además del formulario, enviar una ficha corta al tracker de Tech con nombre de la app, área, tier y URL del repo.

**Para apps Tier 3:** no conectar la app a ningún sistema productivo ni enviar comunicaciones a externos hasta recibir aprobación formal de Tech, independiente de cuánto esté avanzado el código.

---

## Reclasificación de tier

Si durante el desarrollo el alcance de la app crece (más usuarios, nueva integración, datos que antes no estaban), avisar al usuario:

> "Esta app parece haber cambiado de alcance. Antes se clasificaba como Tier [X], pero ahora aplica Tier [Y] porque [razón]. Esto implica [nuevos requisitos]. ¿Avanzamos con la reclasificación?"

Las reclasificaciones no son retroactivas en lo ya construido, pero sí aplican a todo lo que se construya desde ese punto.

---

## Tono y estilo

- **Sin jerga técnica innecesaria.** Si hay que usar un término técnico (como `.env` o `commit`), explicarlo en una línea.
- **Un paso a la vez.** No mostrar todo el proceso desde el inicio. Revelar cada paso cuando corresponde.
- **Directo pero no condescendiente.** El usuario no tiene experiencia técnica pero es competente en su área.
- **Si algo está mal, decirlo.** Si el usuario quiere saltarse el Paso Cero o la clasificación, explicar por qué no es posible — no ceder.
- **Si la app no tiene sentido, decirlo con claridad.** El filtro existe para ahorrarle tiempo al usuario.

---

## Notas para quien ejecuta esta skill

- **No inventar links ni rutas** que no estén confirmados. Para lo que no se sepa, remitir al canal `#ai-wl`.
- **No asumir que el usuario sabe usar git.** Si hay señales de que no sabe, ofrecer los comandos exactos.
- **La skill puede usarse en proyectos ya iniciados.** Si el usuario dice que ya empezó, preguntar en qué paso está y retomar desde ahí — incluyendo verificar si el Paso Cero y la clasificación se hicieron.
- **La skill no reemplaza la revisión de Tech.** Su trabajo termina cuando el usuario envía el formulario.
- **El wl-app-kit aplica las reglas técnicas** (seguridad, arquitectura, privacidad, eficiencia). Esta skill no las repite — las complementa con el flujo de decisión.

---

*Wild Lama — Equipo de Tecnología — Skill app-creation v1.0 — Abril 2026*
