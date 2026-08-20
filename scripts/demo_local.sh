#!/usr/bin/env bash
# Local RAG demo: generates a small synthetic PDF, uploads it, asks a
# known-content question (expects a page citation) and an out-of-scope
# question (expects the fixed "insufficient evidence" message).
#
# Requires the stack to already be running: `docker compose up -d`
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
DEMO_PDF="/tmp/agentic_learning_platform_demo.pdf"

echo "== Generando PDF sintetico de demo =="
uv run python - <<PY
from fpdf import FPDF

pdf = FPDF()
pdf.set_font("Helvetica", size=12)
pdf.add_page()
pdf.multi_cell(
    0, 10,
    "Gestion de Incidentes: El objetivo de la gestion de incidentes es restaurar "
    "el servicio interrumpido lo mas rapido posible, minimizando el impacto en el negocio.",
)
pdf.add_page()
pdf.multi_cell(
    0, 10,
    "Gestion de Problemas: La gestion de problemas busca identificar la causa raiz "
    "de los incidentes recurrentes para prevenir que vuelvan a ocurrir.",
)
pdf.output("${DEMO_PDF}")
print("PDF generado en ${DEMO_PDF}")
PY

echo
echo "== Verificando /ready =="
curl --fail -s "${API_URL}/ready"
echo

echo
echo "== Subiendo el PDF de demo =="
curl --fail -s -X POST "${API_URL}/v1/documents" \
  -F "file=@${DEMO_PDF};type=application/pdf"
echo

echo
echo "== Pregunta con evidencia (se espera cita en pagina 1) =="
curl --fail -s -X POST "${API_URL}/v1/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Qué es la gestión de incidentes?"}'
echo

echo
echo "== Pregunta sin evidencia (se espera mensaje fijo, sin citas) =="
curl --fail -s -X POST "${API_URL}/v1/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Cómo se prepara una paella valenciana?"}'
echo

echo
echo "== Demo visual (widget) =="
echo "PDF cargado. Abre ${API_URL}/demo en un navegador, haz clic en"
echo "'Pregúntale al Tutor' y prueba las mismas dos preguntas para ver la"
echo "respuesta progresiva (streaming) y la cita del documento."

echo
echo "Demo completa."
