"""Port for resolving the authorization scope of an incoming request.

The concrete implementation used in this PR
(``DevHeaderAuthorizationContextProvider``) reads plain, unverified HTTP
headers and is explicitly NOT a real authentication mechanism — see its own
docstring. A future PR can replace it with a real JWT/OIDC-backed provider
behind this same port without touching ``QueryService``, ``IngestionService``,
or the routes that depend on it.
"""

from abc import ABC, abstractmethod

from agentic_learning_platform.domain.models import RequestContext


class IAuthorizationContextProvider(ABC):
    @abstractmethod
    def resolve(
        self, *, organization_id: str | None, course_id: str | None, user_id: str | None
    ) -> RequestContext:
        """Resolve the request's authorization context.

        Raises an ``AppError`` subclass if any of the three is missing or
        blank — never returns a partially-resolved context.
        """
        ...
