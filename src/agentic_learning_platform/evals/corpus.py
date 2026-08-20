"""The synthetic evaluation corpus: a small set of documents authored
specifically for `golden_dataset.v1.json`, spanning direct/paraphrased
questions, same-topic distractors, and deliberate near-duplicate content
across courses and organizations (see docs/architecture.md's PR-005
section). Generated at eval-run time via FPDF (same pattern as
`tests/conftest.py`'s `sample_pdf_bytes` — deterministic, no binary fixture
file, no licensing question) and ingested through the unmodified
`IngestionService`, exactly as `POST /v1/documents` does in production.
"""

from dataclasses import dataclass

from fpdf import FPDF

from agentic_learning_platform.application.services.ingestion_service import IngestionService
from agentic_learning_platform.domain.models import RequestContext

ORG_PRIMARY = "eval-org-primary"
COURSE_ITSM_101 = "eval-course-itsm-101"
COURSE_ITSM_201 = "eval-course-itsm-201"
ORG_SECONDARY = "eval-org-secondary"
COURSE_CROSSORG = "eval-course-crossorg"

EVAL_HARNESS_USER_ID = "eval-harness"


@dataclass(frozen=True, slots=True)
class EvalDocument:
    filename: str
    organization_id: str
    course_id: str
    pages: list[str]


EVAL_CORPUS: list[EvalDocument] = [
    EvalDocument(
        filename="itsm_glossary.pdf",
        organization_id=ORG_PRIMARY,
        course_id=COURSE_ITSM_101,
        pages=[
            "Gestion de Incidentes: El objetivo de la gestion de incidentes es "
            "restaurar el servicio interrumpido lo mas rapido posible, "
            "minimizando el impacto en el negocio.",
            "Gestion de Problemas: La gestion de problemas busca identificar la "
            "causa raiz de los incidentes recurrentes para prevenir que vuelvan "
            "a ocurrir.",
            "Gestion de Cambios: La gestion de cambios controla el proceso de "
            "introducir modificaciones en el entorno de produccion, "
            "minimizando el riesgo de interrupciones no planificadas.",
            "Acuerdo de Nivel de Servicio (SLA): Un SLA define los niveles de "
            "servicio acordados entre el proveedor y el cliente, incluyendo "
            "tiempos de respuesta y disponibilidad garantizada.",
        ],
    ),
    EvalDocument(
        filename="asset_management.pdf",
        organization_id=ORG_PRIMARY,
        course_id=COURSE_ITSM_101,
        pages=[
            "Gestion de Activos: La gestion de activos de TI hace seguimiento "
            "del ciclo de vida completo del hardware y software, desde su "
            "adquisicion hasta su retiro.",
            "Base de Datos de Gestion de Configuracion (CMDB): Es el "
            "repositorio que almacena los elementos de configuracion de TI y "
            "las relaciones entre ellos.",
        ],
    ),
    EvalDocument(
        filename="security_policy.pdf",
        organization_id=ORG_PRIMARY,
        course_id=COURSE_ITSM_101,
        pages=[
            "Politica de Seguridad de la Informacion: Todo empleado debe "
            "reportar cualquier incidente de seguridad sospechoso de "
            "inmediato al equipo de respuesta a incidentes de seguridad.",
        ],
    ),
    EvalDocument(
        filename="sla_and_support.pdf",
        organization_id=ORG_PRIMARY,
        course_id=COURSE_ITSM_101,
        pages=[
            "Niveles de Soporte Tecnico: El soporte se organiza en niveles "
            "(Tier 1, Tier 2, Tier 3); cada nivel escala los casos que no "
            "puede resolver al siguiente nivel con mayor especializacion "
            "tecnica.",
        ],
    ),
    # Same organization as above, a DIFFERENT course — near-duplicate of
    # itsm_glossary.pdf's incident-management page, reworded. Used by the
    # G-cross-course golden cases to prove retrieval never leaks across
    # courses within the same organization, even under near-identical
    # embeddings.
    EvalDocument(
        filename="itsm_glossary_v2.pdf",
        organization_id=ORG_PRIMARY,
        course_id=COURSE_ITSM_201,
        pages=[
            "Gestion de Incidentes (version curso 201): El proposito de "
            "administrar los incidentes es recuperar la operacion del "
            "servicio afectado en el menor tiempo posible y reducir el "
            "impacto sobre las operaciones del negocio.",
        ],
    ),
    # A DIFFERENT organization entirely — same near-duplicate pattern, one
    # level up. Used by the H-cross-org golden cases.
    EvalDocument(
        filename="itsm_glossary_crossorg.pdf",
        organization_id=ORG_SECONDARY,
        course_id=COURSE_CROSSORG,
        pages=[
            "Gestion de Incidentes (organizacion externa): El fin de "
            "gestionar incidentes es reestablecer el servicio afectado "
            "cuanto antes y limitar el impacto en la operacion.",
        ],
    ),
]


def _build_pdf_bytes(pages: list[str]) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for page_text in pages:
        pdf.add_page()
        pdf.multi_cell(0, 10, page_text)
    return bytes(pdf.output())


async def ingest_eval_corpus(ingestion_service: IngestionService) -> None:
    """Ingest every `EVAL_CORPUS` document into its declared organization/
    course scope, via the unmodified production `IngestionService` — no
    different from how `POST /v1/documents` would do it."""
    for document in EVAL_CORPUS:
        content = _build_pdf_bytes(document.pages)
        context = RequestContext(
            organization_id=document.organization_id,
            course_id=document.course_id,
            user_id=EVAL_HARNESS_USER_ID,
        )
        await ingestion_service.ingest(
            content,
            filename=document.filename,
            mime_type="application/pdf",
            context=context,
        )
