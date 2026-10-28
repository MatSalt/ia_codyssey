from typing import Annotated

from fastapi import APIRouter, Depends

from ..dependencies import get_data_repository
from ..models import Summary
from ..ports import DataRepository
from .service import build_summary

router = APIRouter(prefix="/api/data", tags=["summary"])


@router.get("/summary", response_model=Summary)
def get_summary(repo: Annotated[DataRepository, Depends(get_data_repository)]) -> Summary:
    return build_summary(repo.list_records())
