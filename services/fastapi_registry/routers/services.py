"""Service registry CRUD endpoints.

Every route here sits behind the internal-secret dependency: this router is called
by the Django gateway, never by a browser.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.fastapi_registry.database import get_session
from services.fastapi_registry.models import ServiceModel
from services.fastapi_registry.schemas import ServiceCreate, ServiceRead
from services.fastapi_registry.security import verify_internal_secret

router = APIRouter(
    prefix="/services",
    tags=["services"],
    dependencies=[Depends(verify_internal_secret)],
    responses={401: {"description": "Missing or invalid internal credentials"}},
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[ServiceRead])
async def list_services(session: SessionDep) -> list[ServiceModel]:
    """Return every registered service.

    Served straight from services_db rather than by pinging targets, so the
    gateway gets a fast, predictable response. Freshness is the health engine's job.
    """
    result = await session.execute(select(ServiceModel).order_by(ServiceModel.id))
    return list(result.scalars().all())


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
async def create_service(payload: ServiceCreate, session: SessionDep) -> ServiceModel:
    """Register a new service."""
    service = ServiceModel(
        name=payload.name,
        environment=payload.environment.value,
        # HttpUrl is not a str; the column is. Convert explicitly.
        health_check_url=str(payload.health_check_url),
    )
    session.add(service)

    try:
        await session.commit()
    except IntegrityError as exc:
        # Let the database's unique index decide, rather than checking first:
        # a SELECT-then-INSERT races with a concurrent request.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A service named {payload.name!r} already exists",
        ) from exc

    await session.refresh(service)
    return service


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: int, session: SessionDep) -> None:
    """Remove a service from the registry."""
    service = await session.get(ServiceModel, service_id)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No service with id {service_id}",
        )

    await session.delete(service)
    await session.commit()
