# Open Source Discovery — Agentic Learning Platform

Investigación del ecosistema Open Source para decidir qué reutilizar y qué construir en el MVP. Todos los datos (licencia, stars, último commit) fueron verificados en vivo contra la API de GitHub el **2026-08-06** — no provienen de memoria del modelo, que puede estar desactualizada. No se incluye ningún repositorio archivado, abandonado o de mantenimiento personal sin adopción real.

**Alcance de esta investigación** (reducido deliberadamente por decisión explícita, tras una primera pasada demasiado amplia): 10 categorías directamente relevantes para el MVP, 3 proyectos ganadores por categoría. Categorías de Fase 2 (multimodal, video, OCR, chunking, embeddings, hybrid search, citation generation, guardrails, agent memory, multi-tenant RAG como repos dedicados) quedan fuera de esta ronda — se investigan cuando esas fases se planifiquen.

---

## 1. RAG Framework

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| langchain | https://github.com/langchain-ai/langchain | MIT | 143,557 | 2026-08-06 |
| llama_index | https://github.com/run-llama/llama_index | MIT | 51,424 | 2026-08-04 |
| haystack | https://github.com/deepset-ai/haystack | Apache-2.0 | 26,130 | 2026-08-06 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| langchain | Capa común de integraciones LLM/embeddings/retrievers/tools; ecosistema de facto para conectar proveedores. | Sus integraciones de bajo nivel indirectamente, vía `langchain-aws` (cliente de Bedrock) — no el framework de alto nivel. | Sus abstracciones de "chain"/"agent" de alto nivel: ya decidimos LangGraph + puertos propios para evitar una segunda capa de abstracción redundante. | Alta, pero solo como dependencia transitiva de `langchain-aws`, no como framework de orquestación. |
| llama_index | Indexación y consulta de documentos con muchos parsers/retrievers integrados out-of-the-box. | Sus patrones de "citation query engine" como referencia conceptual de diseño. | Su motor de indexación/vector-store abstraction completo: duplicaría nuestro `PgVectorStoreAdapter` a medida. | Media — competiría con nuestra propia capa de retrieval si se adoptara completo. |
| haystack | Pipelines de RAG/agentes explícitos, orientado a producción. | Su patrón de pipeline explícito (retrieve→rank→generate) como referencia de diseño. | Su DSL de pipeline completo: duplicaría LangGraph. | Media-baja — redundante con la orquestación que ya decidimos. |

**Recomendación**: ningún framework de RAG se adopta completo. Ya se decidió (arquitectura aprobada) usar LangGraph + puertos propios, evitando una segunda capa de abstracción. `langchain` entra solo indirectamente vía `langchain-aws`. LlamaIndex/Haystack quedan como referencia de patrones, no como dependencias.

---

## 2. LangGraph

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| langgraph | https://github.com/langchain-ai/langgraph | MIT | 39,036 | 2026-08-06 |
| langgraph-supervisor-py | https://github.com/langchain-ai/langgraph-supervisor-py | MIT | 1,637 | 2026-07-15 |
| agent-chat-ui | https://github.com/langchain-ai/agent-chat-ui | MIT | 3,040 | 2026-08-03 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| langgraph | Orquestación de agentes como grafos de estado con checkpointer persistente. Incluye el paquete oficial `langgraph-checkpoint-postgres` dentro del mismo monorepo (`libs/checkpoint-postgres`) — no es un repo aparte. | El framework completo (ya es decisión arquitectónica) + el checkpointer Postgres oficial. | Nada — es dependencia directa, no código a copiar. | Total: es la pieza central de la arquitectura ya aprobada. |
| langgraph-supervisor-py | Patrón oficial de "agente supervisor" para coordinar múltiples sub-agentes. | El patrón conceptual, para una eventual Fase 2 (ej. sub-agente de video/timestamps). | Adoptarlo ya en el MVP: nuestro grafo es de un solo agente lineal, un supervisor sería sobreingeniería prematura. | Baja ahora, alta en fases futuras. |
| agent-chat-ui | App de referencia oficial para chatear con cualquier agente LangGraph vía streaming. | El contrato de eventos de streaming como referencia de diseño para nuestro propio esquema SSE. | El código completo de la app (es una app Next.js standalone, no un widget embebible). | Media — referencia, no dependencia. |

**Recomendación**: **langgraph** (core + `checkpoint-postgres`) es la única adopción real de esta categoría — ya es la base de la arquitectura aprobada. Los otros dos quedan como patrones de referencia para fases posteriores.

---

## 3. AWS Bedrock

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| amazon-bedrock-samples | https://github.com/aws-samples/amazon-bedrock-samples | MIT-0 | 1,485 | 2026-08-04 |
| langchain-aws | https://github.com/langchain-ai/langchain-aws | MIT | 337 | 2026-08-05 |
| generative-ai-cdk-constructs | https://github.com/awslabs/generative-ai-cdk-constructs | Apache-2.0 | 541 | 2026-08-06 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| amazon-bedrock-samples | Colección oficial de AWS con ejemplos de cada modelo/capability de Bedrock (notebooks). | Patrones de llamada (streaming, formato de prompt, Knowledge Bases) como referencia — MIT-0 permite copiar literal sin atribución. | No es una dependencia instalable (son notebooks), no se importa como librería. | Media — referencia, no dependencia. |
| langchain-aws | Integración instalable de Bedrock (chat + embeddings) con LangChain/LangGraph. | El paquete completo como dependencia directa (`ChatBedrockConverse`, embeddings Titan). | Nada, se instala vía `uv add`. | **Total** — es literalmente el cliente Bedrock del nodo `generate_answer`. |
| generative-ai-cdk-constructs | Constructs de AWS CDK (no Terraform) para patrones de IA generativa (Knowledge Bases, agentes). | Los patrones de arquitectura documentados (cómo estructuran KB + Aurora/OpenSearch) como inspiración de diseño. | El código CDK en sí: el proyecto usa Terraform, no CDK (restricción explícita). | Baja como dependencia, media como referencia arquitectónica. |

**Recomendación**: **langchain-aws** es la única dependencia de código real de esta categoría. `amazon-bedrock-samples` como referencia de patrones de prompting/streaming.

---

## 4. PostgreSQL + pgvector

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| pgvector | https://github.com/pgvector/pgvector | PostgreSQL License (permisiva, estilo BSD) | 22,514 | 2026-08-04 |
| pgvector-python | https://github.com/pgvector/pgvector-python | MIT | 1,511 | 2026-07-06 |
| pgvectorscale | https://github.com/timescale/pgvectorscale | PostgreSQL License | 3,102 | 2026-04-30 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| pgvector | Extensión de Postgres para búsqueda por similitud vectorial (HNSW/IVFFlat). | La extensión completa, habilitada en RDS/Aurora — es un requisito explícito y fijo del producto. | N/A — es una extensión de BD, no hay código de aplicación que copiar. | **Total** — requisito no negociable del producto. |
| pgvector-python | Cliente Python (psycopg/SQLAlchemy/asyncpg/Django) para el tipo `vector`. | El tipo `Vector` directamente en nuestro `PgVectorStoreAdapter`, evita escribir el mapeo SQL↔Python a mano. | No incluye lógica de RAG/chunking — es un cliente delgado, no hay nada que evitar. | Alta — ahorra trabajo de serialización. |
| pgvectorscale | Índice StreamingDiskANN de alto rendimiento, complementario a pgvector para escala muy grande. | Evaluarlo si el corpus de chunks crece a millones de filas (no es el caso del MVP). | Adoptarlo ya: agrega una extensión más de la que el MVP no necesita a escala de piloto — sobreingeniería temprana. | Baja ahora; alta como ruta de escalado documentada. |

**Recomendación**: **pgvector** (extensión, fija) + **pgvector-python** (cliente) para el MVP. `pgvectorscale` se documenta como ruta de escalado futuro, no se adopta todavía.

---

## 5. Parsing de PDF

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| docling | https://github.com/docling-project/docling | MIT | 64,336 | 2026-08-06 |
| pdfplumber | https://github.com/jsvine/pdfplumber | MIT | 10,634 | 2026-08-06 |
| pypdf | https://github.com/py-pdf/pypdf | BSD-3-Clause | 10,146 | 2026-08-06 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| docling | Parser multi-formato (PDF, DOCX, PPTX, XLSX, HTML) con comprensión de layout y tablas; mantenido bajo la Linux Foundation AI & Data (originado en IBM Research). | El parser completo para extracción de texto+tablas+layout — cubre PDF ahora **y** DOCX/PPTX/XLSX en fases posteriores sin cambiar de librería. | Su propio pipeline de chunking/embedding si lo incluye: nuestro chunking por página con citación exacta es a medida. | Alta — cubre el MVP y el roadmap post-MVP sin reescritura. |
| pdfplumber | Extracción de texto/tablas con acceso preciso a coordenadas por carácter y página. | Como motor complementario cuando se necesite precisión de coordenadas de página/tabla más fina que la de Docling. | No tiene comprensión de layout tan rica como Docling en documentos complejos multi-columna. | Alta, especialmente para el caso "página → texto/tabla" exacto. |
| pypdf | Librería pura Python (sin dependencias binarias) para leer/manipular PDF. | Como fallback ligero si el parser principal falla en un PDF particular, o para metadata/conteo de páginas. | Su extracción de texto es más básica que Docling/pdfplumber en layouts complejos. | Media, como complemento, no como motor principal. |

**Riesgo evitado documentado**: `pymupdf/PyMuPDF` (10,415★, muy popular) fue evaluado y **descartado deliberadamente** — licencia **AGPL-3.0** (copyleft fuerte, complica su uso en un producto comercial sin licencia comercial de Artifex). No entra en el top 3 por licencia, no por calidad técnica.

**Recomendación**: **docling** como parser principal (cubre PDF ahora y el roadmap DOCX/PPTX/XLSX). **pdfplumber** como motor complementario para citación de página/tabla de máxima precisión.

---

## 6. FastAPI

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| fastapi | https://github.com/fastapi/fastapi | MIT | 101,361 | 2026-08-06 |
| full-stack-fastapi-template | https://github.com/fastapi/full-stack-fastapi-template | MIT | 44,632 | 2026-08-06 |
| uvicorn | https://github.com/Kludex/uvicorn | BSD-3-Clause | 10,886 | 2026-08-05 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| fastapi | Framework web ASGI tipado con generación automática de OpenAPI. | El framework completo — ya es requisito fijo y base de PR-001. | Nada, es la base del proyecto. | **Total.** |
| full-stack-fastapi-template | Template oficial full-stack (FastAPI+React+SQLModel+Postgres+Docker+CI), ahora bajo la propia org FastAPI. | Patrones de estructura/Dockerfile/CI como referencia (ya aplicados de forma independiente en PR-001). | El frontend React/SQLModel incluido: usamos nuestro propio widget y Pydantic Settings. | Media — referencia de convenciones, no dependencia. |
| uvicorn | Servidor ASGI de alto rendimiento (repo trasladado de `encode/` al mantenedor principal, sigue activo). | Como dependencia directa (`uvicorn[standard]`) — ya en `pyproject.toml`. | Nada que copiar. | **Total**, ya es dependencia de producción. |

**Recomendación**: **fastapi** + **uvicorn** son dependencias directas ya en uso desde PR-001. `full-stack-fastapi-template` queda como referencia de convenciones, no como dependencia.

---

## 7. Terraform para AWS

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| terraform-provider-aws | https://github.com/hashicorp/terraform-provider-aws | MPL-2.0 | 11,026 | 2026-08-06 |
| terraform-aws-rds | https://github.com/terraform-aws-modules/terraform-aws-rds | Apache-2.0 | 958 | 2026-03-27 |
| terraform-aws-bedrock | https://github.com/aws-ia/terraform-aws-bedrock | Apache-2.0 | 85 | 2025-12-30 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| terraform-provider-aws | Provider oficial de Terraform para todos los recursos AWS. | El provider completo — base obligatoria de cualquier Terraform contra AWS. | Nada, es el provider en sí. | **Total.** |
| terraform-aws-rds | Módulo comunitario maduro (org ampliamente adoptada en la industria) para provisionar RDS/Aurora. | El módulo completo para la Aurora PostgreSQL+pgvector del MVP. | La configuración por defecto sin revisar: hay que ajustar `parameter_group` explícitamente para habilitar la extensión `vector`. | Alta — evita escribir el recurso RDS y sus dependencias a mano. |
| terraform-aws-bedrock | Módulo oficial del equipo AWS Integration & Automation para recursos de Bedrock (Knowledge Bases, Agents, Guardrails) vía Terraform. | Como referencia si en el futuro se activa el modo alterno de Bedrock Knowledge Bases. | Adoptarlo completo en el MVP: resuelve más de lo que necesitamos (el MVP solo necesita `bedrock:InvokeModel*` vía IAM, no Knowledge Bases/Agents). | Baja-media ahora; útil si se activa el modo alterno documentado en la arquitectura. |

**Riesgo a notar**: "Terraform + Bedrock" es una categoría delgada — una búsqueda amplia de `terraform-bedrock` devuelve casi exclusivamente repos personales con **0 estrellas**, confirmado en vivo. El único módulo de un equipo AWS reconocido (`aws-ia/terraform-aws-bedrock`) tiene adopción todavía modesta (85★) y último push hace ~7 meses — vigilar su evolución antes de depender de él más allá de referencia.

**Recomendación**: **terraform-provider-aws** (obligatorio) + **terraform-aws-rds** cubren el MVP real. `terraform-aws-bedrock` queda documentado, no adoptado.

---

## 8. Widget de chat embebible

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| CopilotKit | https://github.com/CopilotKit/CopilotKit | MIT | 36,533 | 2026-08-06 |
| assistant-ui | https://github.com/assistant-ui/assistant-ui | MIT | 11,474 | 2026-08-06 |
| ai (Vercel AI SDK) | https://github.com/vercel/ai | Apache-2.0 | 26,048 | 2026-08-06 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| CopilotKit | Stack frontend para UI generativa de agentes (React/Angular/mobile); creadores del protocolo AG-UI. | Componentes de chat/streaming como base si se relajara la decisión de Web Component vanilla. | El protocolo AG-UI completo como dependencia obligatoria — ya se decidió un esquema SSE propio, no AG-UI. | Media-alta si se reconsidera React; conceptualmente muy alineado. |
| assistant-ui | Librería TS/React dedicada a UI de chat con IA (streaming, markdown, citas). | Componentes de renderizado de streaming/citas como referencia de UX. | Requiere React como runtime completo — nuestra decisión de Web Component aislado es más ligera para incrustar en un portal de terceros. | Media — buena referencia de UX, no la base técnica elegida. |
| ai (Vercel AI SDK) | SDK TS con hooks de UI (`useChat`) para consumo de streaming, muy adoptado y documentado. | El patrón de manejo de streaming SSE en cliente, como referencia de implementación. | Su contrato de protocolo de streaming propio — ya decidimos un esquema de eventos propio. | Media — referencia de patrón, no dependencia directa. |

**Recomendación**: ninguno se adopta como dependencia completa — la arquitectura aprobada ya decidió Web Component vanilla + esquema SSE propio, precisamente para no depender de un framework de widget de terceros ni de React como runtime obligatorio en el portal anfitrión. **CopilotKit** es la referencia de UX/patrones más cercana a estudiar antes de construir el widget propio.

---

## 9. LLM Evals

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| ragas | https://github.com/vibrantlabsai/ragas | Apache-2.0 | 15,161 | 2026-02-24 |
| deepeval | https://github.com/confident-ai/deepeval | Apache-2.0 | 17,444 | 2026-08-06 |
| promptfoo | https://github.com/promptfoo/promptfoo | MIT | 24,003 | 2026-08-06 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| ragas | Métricas de evaluación específicas de RAG (faithfulness, context precision/recall, answer relevancy). | Las métricas de faithfulness/context precision directamente en nuestro harness de evals — mapean 1:1 con "groundedness"/"citation accuracy". | Su integración por defecto con LangChain si genera fricción — usar solo las funciones de métrica. | Alta — pieza más directamente reutilizable para el quality gate. Nota: org renombrada recientemente (antes `explodinggradients/ragas`) y cadencia más lenta (~5 meses desde el último push) — vigilar. |
| deepeval | Framework de evaluación "estilo pytest" para LLMs, con métricas RAG y ejecución nativa en CI. | La estructura de test-cases + aserciones como patrón para el quality gate de GitHub Actions. | Su plataforma SaaS de reporting (Confident AI) — usar solo la librería open-source. | Alta — mantenimiento más activo que ragas, integración CI más directa. |
| promptfoo | CLI declarativo para testear prompts/agentes/RAG y red-teaming de seguridad, con CI/CD nativo. | Configuración declarativa para el golden-set + escaneo de vulnerabilidades de prompt injection. | No sustituye las métricas específicas de RAG de ragas/deepeval — es más genérico, se usa en conjunto. | Alta — cubre también parte de la necesidad de guardrails/seguridad. |

**Recomendación**: **deepeval** para el quality gate de CI (integración pytest-like, mantenimiento más activo) + **ragas** para las métricas específicas de faithfulness/groundedness. `promptfoo` como capa adicional de seguridad/red-teaming.

---

## 10. Observabilidad para LLMs

| Nombre | GitHub URL | Licencia | Stars | Último commit |
|---|---|---|---|---|
| langfuse | https://github.com/langfuse/langfuse | MIT (núcleo); `ee/` bajo licencia separada | 32,625 | 2026-08-06 |
| phoenix | https://github.com/Arize-ai/phoenix | Elastic License 2.0 (source-available, no OSI) | 10,921 | 2026-08-06 |
| openllmetry | https://github.com/traceloop/openllmetry | Apache-2.0 | 7,359 | 2026-08-04 |

| Nombre | Qué resuelve | Qué reutilizaríamos | Qué NO reutilizaríamos | Compatibilidad con nuestro MVP |
|---|---|---|---|---|
| langfuse | Plataforma de ingeniería LLM completa (tracing, evals, gestión de prompts, datasets), integra con OpenTelemetry/LangChain/LiteLLM. | El núcleo self-hosted (MIT) completo para tracing y dashboards de costo/latencia. | Las funcionalidades bajo `ee/` (Enterprise Edition) sin revisar su licencia por separado. | Alta — elección natural, ya usada como patrón de casa (ambos repos legacy de referencia la usaban). |
| phoenix | Observabilidad/evaluación nativa de OpenTelemetry, de una empresa reconocida de ML observability. | Como alternativa si se prefiere un enfoque más OTel-puro. | Ofrecerlo como servicio hospedado a terceros — lo prohíbe expresamente la Elastic License 2.0 (uso interno self-hosted sí está permitido). | Media — viable, pero con una restricción de licencia que langfuse no tiene. |
| openllmetry | Instrumentación pura basada en convenciones semánticas de OpenTelemetry para GenAI, sin ser una plataforma propia. | Como capa de instrumentación complementaria a langfuse para exportar a múltiples backends (patrón multi-backend ya usado en el proyecto de referencia). | No sustituye la UI/dashboard de langfuse, solo instrumenta. | Alta como complemento, no como plataforma principal. |

**Recomendación**: **langfuse** (núcleo MIT) como plataforma principal — ya es el patrón de casa. **openllmetry** como capa de instrumentación OTel complementaria, replicando el patrón multi-backend ya documentado en `docs/architecture.md`.

---

## Matriz final de decisión

| Componente | Repositorio recomendado | Por qué gana | Nivel de confianza |
|---|---|---|---|
| Orquestación | langchain-ai/langgraph | Ya es decisión arquitectónica fija; incluye el checkpointer Postgres oficial que usaremos directamente. | Alto |
| Cliente Bedrock | langchain-ai/langchain-aws | Único paquete instalable (no solo notebooks de ejemplo) que integra Bedrock con LangGraph/LangChain de forma mantenida. | Alto |
| Vector store | pgvector/pgvector + pgvector/pgvector-python | Requisito fijo del producto; el cliente Python evita reinventar el mapeo de tipos. | Alto |
| Parsing de documentos | docling-project/docling | Único parser que cubre PDF ahora y DOCX/PPTX/XLSX (roadmap) sin cambiar de librería; gobernanza sólida (Linux Foundation). | Alto |
| Extracción de precisión | jsvine/pdfplumber | Complementa a Docling cuando se necesita coordenada exacta de página/tabla. | Medio-alto |
| Backend HTTP | fastapi/fastapi + Kludex/uvicorn | Ya en uso desde PR-001; sin alternativa considerada. | Alto |
| IaC AWS | hashicorp/terraform-provider-aws + terraform-aws-modules/terraform-aws-rds | Provider obligatorio + módulo Aurora maduro y ampliamente adoptado. | Alto |
| Widget embebible | Ninguno (build propio) | La arquitectura ya decidió Web Component vanilla + SSE propio para no depender de React ni de un protocolo de terceros; CopilotKit como referencia de UX. | Medio (decisión de diseño, no de reutilización directa) |
| Evals | confident-ai/deepeval + vibrantlabsai/ragas | deepeval para el quality gate de CI; ragas para las métricas de faithfulness/groundedness específicas de RAG. | Alto |
| Observabilidad LLM | langfuse/langfuse | Patrón de casa ya validado en los repos de referencia; núcleo MIT suficiente para el MVP. | Alto |

---

## Componentes descartados y por qué

| Componente | Razón del descarte |
|---|---|
| timescale/pgai | **Archivado** (`archived: true` confirmado vía API) — no se incluye pese a tener 5,811★, viola la regla explícita de no usar repos abandonados. |
| pymupdf/PyMuPDF | Licencia **AGPL-3.0** — copyleft fuerte, riesgo legal para un producto comercial sin licencia comercial de Artifex. Técnicamente competitivo (10,415★) pero descartado por licencia. |
| run-llama/llama_index, deepset-ai/haystack (como framework completo) | Duplicarían la capa de orquestación que LangGraph ya cubre — adoptarlos completos sería sobreingeniería (doble abstracción). |
| langchain (framework de alto nivel: chains/agents) | Ya se decidió no usar LangChain más allá del cliente Bedrock (`langchain-aws`), para evitar una segunda capa de abstracción sobre nuestros propios puertos. |
| awslabs/generative-ai-cdk-constructs (como dependencia) | Usa AWS CDK, no Terraform — el proyecto tiene Terraform como IaC fijo. Queda solo como referencia de arquitectura. |
| aws-ia/terraform-aws-bedrock (en el MVP) | Resuelve Knowledge Bases/Agents, que no están en el MVP (el MVP solo necesita `bedrock:InvokeModel*` vía IAM). Se documenta para el modo alterno futuro. |
| timescale/pgvectorscale (en el MVP) | Resuelve escala de millones de filas; el MVP opera a escala de piloto — adoptarlo ahora sería sobreingeniería temprana. |
| CopilotKit, assistant-ui, Vercel AI SDK (como dependencia del widget) | La arquitectura ya decidió Web Component vanilla + esquema SSE propio, específicamente para no imponer React en el portal anfitrión ni adoptar un protocolo de streaming de terceros. Quedan como referencia de UX únicamente. |
| Arize-ai/phoenix (como plataforma principal) | Licencia Elastic License 2.0 (source-available, no OSI) prohíbe ofrecerlo como servicio hospedado a terceros — langfuse (MIT en el núcleo) no tiene esa restricción y ya es el patrón de casa. |
| promptfoo, openllmetry (como plataforma principal) | Son complementos (seguridad/red-teaming e instrumentación OTel respectivamente), no sustitutos de ragas/deepeval ni de langfuse como plataforma. |

---

## Riesgos identificados en esta investigación

1. **"Terraform + Bedrock" es un ecosistema delgado**: la mayoría de resultados de búsqueda son repos personales de 0 estrellas; el único módulo de un equipo AWS reconocido tiene adopción modesta y ~7 meses desde el último push. No depender de él más allá de referencia hasta que madure.
2. **ragas cambió de organización** (`explodinggradients` → `vibrantlabsai`) y su cadencia de commits es más lenta que deepeval/promptfoo — vigilar continuidad del proyecto antes de comprometerse a largo plazo únicamente con esta librería para evals.
3. **Licencias no siempre son lo que el badge de GitHub sugiere**: `pgvector`, `pypdf` y `vercel/ai` mostraban `NOASSERTION`/ambiguo en metadata automática de GitHub — se verificó el archivo `LICENSE` real en cada caso (PostgreSQL License, BSD-3-Clause y Apache-2.0 respectivamente). No confiar en el campo de licencia de la API sin verificar el archivo cuando aparezca `NOASSERTION` o "Other".
4. **Langfuse tiene un modelo open-core**: el núcleo es MIT, pero directorios `ee/` tienen licencia separada — revisar `ee/LICENSE` antes de habilitar cualquier feature marcada como Enterprise Edition.
5. **Arize Phoenix usa Elastic License 2.0**, no una licencia OSI — uso interno self-hosted está permitido, pero ofrecerlo como servicio a terceros no. Relevante solo si se reconsiderara como alternativa a langfuse.
6. **PyMuPDF (AGPL-3.0) es probablemente la librería de parsing de PDF más popular por adopción individual**, pero inadecuada para uso comercial sin licencia paga — riesgo de que un ingeniero la agregue por costumbre sin revisar la licencia; documentar la exclusión explícitamente en las guías de contribución del repo.

---

## Recomendaciones

- Adoptar como dependencias directas del MVP: `langgraph` (+ `checkpoint-postgres`), `langchain-aws`, `pgvector` + `pgvector-python`, `docling` (+ `pdfplumber` complementario), `fastapi` + `uvicorn`, `terraform-provider-aws` + `terraform-aws-rds`, `deepeval` + `ragas`, `langfuse`.
- No adoptar ningún framework de widget de terceros ni de RAG de alto nivel — construir ambas piezas a medida sobre los puertos ya definidos en la arquitectura aprobada, usando los repos investigados solo como referencia de patrones/UX.
- Revisar la licencia real (no solo el badge automático de GitHub) de cualquier nueva dependencia antes de agregarla — esta investigación encontró 3 casos de metadata ambigua que requirieron verificación manual del archivo `LICENSE`.
- Reevaluar `pgvectorscale` y `terraform-aws-bedrock` cuando el proyecto pase de piloto a producción a escala, no antes.

---

## Arquitectura recomendada del MVP (usando únicamente los componentes de esta investigación)

```
┌─────────────────────────────────────────────────────────────────┐
│  Widget embebible (Web Component propio, sin dependencia externa)│
│  Referencia de UX: CopilotKit, assistant-ui, Vercel AI SDK        │
└───────────────────────────┬───────────────────────────────────────┘
                            │ SSE (esquema propio)
┌───────────────────────────▼───────────────────────────────────────┐
│  fastapi/fastapi + Kludex/uvicorn                                 │
│  (app factory ya implementada en PR-001)                          │
└───────────────────────────┬───────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────┐
│  langchain-ai/langgraph                                            │
│  grafo: validate→retrieve→evaluate→generate→cite→persist           │
│  checkpointer: langgraph-checkpoint-postgres                       │
└──────┬──────────────────────────────────────────┬──────────────────┘
       │                                          │
┌──────▼──────────────────┐          ┌────────────▼─────────────────┐
│ langchain-ai/langchain-aws│          │ pgvector/pgvector +           │
│ → AWS Bedrock (chat +     │          │ pgvector/pgvector-python      │
│   embeddings Titan V2)    │          │ (Aurora PostgreSQL)           │
└────────────────────────────┘          └────────────────────────────┘
       ▲
       │ ingesta (pipeline nuevo, sin dependencia OSS específica salvo parsing)
┌──────┴──────────────────────────────────────────────────────────────┐
│  Pipeline de ingesta: docling-project/docling (parser principal)     │
│                       + jsvine/pdfplumber (precisión de página/tabla)│
└───────────────────────────────────────────────────────────────────────┘

Infraestructura (Terraform):
  hashicorp/terraform-provider-aws + terraform-aws-modules/terraform-aws-rds
  → Aurora PostgreSQL con extensión pgvector habilitada

Calidad (CI):
  confident-ai/deepeval + vibrantlabsai/ragas → quality gate de citation-accuracy/groundedness

Observabilidad:
  langfuse/langfuse (núcleo MIT) → tracing + costo + evals interactivas
```

**Por qué cada componente fue elegido** (resumen, detalle completo en las secciones 1-10 arriba):

- **langgraph**: ya es la decisión arquitectónica del proyecto; verificado como activamente mantenido (39k★, push diario) e incluye el checkpointer Postgres que necesitamos sin código adicional.
- **langchain-aws**: es el único paquete instalable (no solo ejemplos) que conecta LangGraph con Bedrock de forma mantenida por el mismo equipo que mantiene LangGraph.
- **pgvector + pgvector-python**: pgvector es requisito fijo del producto; el cliente Python evita escribir el mapeo de tipos SQL↔Python a mano.
- **docling + pdfplumber**: docling cubre el roadmap completo de formatos (PDF ahora, DOCX/PPTX/XLSX después) con la gobernanza más sólida de todo el ecosistema investigado (Linux Foundation, 64k★); pdfplumber complementa cuando se necesita coordenada exacta de página para la cita.
- **fastapi + uvicorn**: ya en uso desde PR-001, sin alternativa evaluada — es un requisito fijo.
- **terraform-provider-aws + terraform-aws-rds**: provider obligatorio + el módulo Aurora más adoptado de la industria, evita escribir el recurso RDS y sus dependencias (subnets, parameter groups, security groups) a mano.
- **Ningún framework de widget de terceros**: la decisión de Web Component vanilla + SSE propio, ya tomada en la arquitectura aprobada, se confirma como correcta tras esta investigación — ningún widget OSS evaluado permite incrustarse en un portal de terceros sin imponer React como runtime o un protocolo de streaming ajeno.
- **deepeval + ragas**: cubren exactamente el requisito de quality gate en CI (deepeval, estilo pytest) y las métricas específicas de groundedness/faithfulness (ragas) que el producto necesita medir.
- **langfuse**: ya es el patrón de observabilidad usado en los repos de referencia auditados al inicio de este proyecto; su núcleo MIT es suficiente para el MVP sin tocar las funcionalidades Enterprise Edition.

No se propone ningún componente sin mantenimiento activo verificado, ni ninguna librería inventada.
