"""Development-only authorization context provider.

Reads ``organization_id``/``course_id``/``user_id`` directly from
caller-supplied values (HTTP headers ``X-Organization-Id``, ``X-Course-Id``,
``X-User-Id`` — extracted by ``routes.authorization``) with NO verification
of who the caller actually is. This is a **development authorization
context / trusted local context**, not authentication, and must never be
treated as safe for a production deployment.

It exists so PR-004's corpus isolation can be built, wired, and tested
end-to-end before the portal's real identity mechanism (Cognito/OIDC/JWT —
not yet decided) is known. A future PR replaces this adapter with one that
derives ``RequestContext`` from a verified token instead of trusting
client-supplied headers; ``QueryService``/``IngestionService``/the domain
never need to change when that happens — see
``application.ports.authorization_context_port``.
"""

from agentic_learning_platform.application.ports.authorization_context_port import (
    IAuthorizationContextProvider,
)
from agentic_learning_platform.domain.models import RequestContext
from agentic_learning_platform.exceptions import MissingAuthorizationContextError

_HEADER_NAMES = ("X-Organization-Id", "X-Course-Id", "X-User-Id")


class DevHeaderAuthorizationContextProvider(IAuthorizationContextProvider):
    def resolve(
        self, *, organization_id: str | None, course_id: str | None, user_id: str | None
    ) -> RequestContext:
        # Stripped before the blank check (not just at the end): a
        # whitespace-only header ("   ") is falsy only *after* stripping, and
        # the resolved RequestContext must carry normalized values, with no
        # accidental external whitespace, in either case.
        stripped_organization_id = organization_id.strip() if organization_id else None
        stripped_course_id = course_id.strip() if course_id else None
        stripped_user_id = user_id.strip() if user_id else None

        values = (stripped_organization_id, stripped_course_id, stripped_user_id)
        if not all(values):
            missing = [name for name, value in zip(_HEADER_NAMES, values, strict=True) if not value]
            raise MissingAuthorizationContextError(
                f"Missing required development authorization header(s): {', '.join(missing)}. "
                "These headers are a DEV-ONLY trusted local context, not real authentication."
            )
        assert (
            stripped_organization_id and stripped_course_id and stripped_user_id
        )  # narrows for pyright
        return RequestContext(
            organization_id=stripped_organization_id,
            course_id=stripped_course_id,
            user_id=stripped_user_id,
        )
