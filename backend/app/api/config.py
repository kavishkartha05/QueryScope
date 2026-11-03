from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_principal
from app.core.config import settings

router = APIRouter(tags=["config"], dependencies=[Depends(get_principal)])


class TargetOption(BaseModel):
    label: str
    url: str


class CapsOut(BaseModel):
    max_num_requests: int
    max_concurrency: int
    max_request_timeout_s: float
    run_wall_clock_limit_s: float


class ConfigResponse(BaseModel):
    caps: CapsOut
    targets: list[TargetOption]
    # True when the allowlist is off (local use): the UI may offer a free URL.
    allow_custom_target: bool
    llm_benchmark_enabled: bool
    auth_enabled: bool


def _targets() -> list[TargetOption]:
    """One option per allowed host, with a sensible default URL for each."""
    demo_host = (urlsplit(settings.demo_target_url).hostname or "").lower()
    options: list[TargetOption] = []
    for host in settings.allowed_target_host_list:
        if demo_host and host == demo_host:
            options.append(TargetOption(label="QueryScope demo target", url=settings.demo_target_url))
        elif host == "httpbin.org":
            options.append(TargetOption(label="httpbin.org", url="https://httpbin.org/get"))
        else:
            options.append(TargetOption(label=host, url=f"https://{host}/"))
    return options


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    # Public limits only: nothing here is a secret, and no resolved addresses.
    return ConfigResponse(
        caps=CapsOut(
            max_num_requests=settings.max_num_requests,
            max_concurrency=settings.max_concurrency,
            max_request_timeout_s=settings.max_request_timeout_s,
            run_wall_clock_limit_s=settings.run_wall_clock_limit_s,
        ),
        targets=_targets(),
        allow_custom_target=not settings.allowlist_enforced,
        llm_benchmark_enabled=settings.llm_benchmark_active,
        auth_enabled=settings.auth_enabled,
    )
