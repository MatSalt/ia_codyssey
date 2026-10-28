from fastapi import APIRouter, Depends, Response, status
from ..dependencies import get_data_repository
from ..models import ISODate, Record, RecordCreate, RecordUpdate
from ..ports import DataRepository
from .service import DataService

router = APIRouter(prefix='/api/data', tags=['data'])


def get_data_service(repo: DataRepository = Depends(get_data_repository)) -> DataService:
    return DataService(repo)


@router.get('', response_model=dict[str, list[Record]])
def list_records(service: DataService = Depends(get_data_service)):
    return {'items': service.list_records()}


@router.post('', response_model=Record, status_code=status.HTTP_201_CREATED)
def create(record: RecordCreate, service: DataService = Depends(get_data_service)):
    return service.create(record)


@router.put('/{record_id}', response_model=Record)
def update(record_id: ISODate, patch: RecordUpdate, service: DataService = Depends(get_data_service)):
    return service.update(record_id.isoformat(), patch)


@router.delete('/{record_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete(record_id: ISODate, service: DataService = Depends(get_data_service)):
    service.delete(record_id.isoformat())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
