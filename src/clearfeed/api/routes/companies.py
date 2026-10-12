from fastapi import APIRouter

from clearfeed.api.deps import SessionDep
from clearfeed.schemas import CompanyOut
from clearfeed.services import agents

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("")
def list_companies(session: SessionDep) -> list[CompanyOut]:
    return [CompanyOut.model_validate(c) for c in agents.list_companies(session)]
