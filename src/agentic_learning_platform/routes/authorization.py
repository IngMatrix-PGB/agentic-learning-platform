"""Shared FastAPI dependency for resolving the (development-only) request
authorization context — used identically by `/v1/documents`, `/v1/query`,
and `/v1/query/stream` so all three enforce the exact same organization/
course scope resolution rule. See
``infrastructure.authorization.dev_header_provider``
for why these headers are NOT real authentication.
"""

from typing import Annotated

from fastapi import Depends, Header, Request

from agentic_learning_platform.application.ports.authorization_context_port import (
    IAuthorizationContextProvider,
)
from agentic_learning_platform.domain.models import RequestContext


def get_authorization_context_provider(request: Request) -> IAuthorizationContextProvider:
    return request.app.state.authorization_context_provider


def get_request_context(
    provider: Annotated[IAuthorizationContextProvider, Depends(get_authorization_context_provider)],
    x_organization_id: Annotated[str | None, Header()] = None,
    x_course_id: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
) -> RequestContext:
    return provider.resolve(
        organization_id=x_organization_id, course_id=x_course_id, user_id=x_user_id
    )
