from fastapi import APIRouter, Depends, Response, status
from ..dependencies import get_conversation_repository
from ..models import Conversation, ConversationCreate, ConversationListItem
from ..ports import ConversationRepository
from .service import ConversationService

router = APIRouter(prefix='/api/conversations', tags=['conversations'])


def get_conversation_service(repo: ConversationRepository = Depends(get_conversation_repository)):
    return ConversationService(repo)


@router.post('', response_model=Conversation, status_code=status.HTTP_201_CREATED)
def create(payload: ConversationCreate, service=Depends(get_conversation_service)):
    return service.create(payload)


@router.get('', response_model=dict[str, list[ConversationListItem]])
def list_conversations(service=Depends(get_conversation_service)):
    return {'items': service.list_conversations()}


@router.get('/{conversation_id}', response_model=Conversation)
def get(conversation_id: str, service=Depends(get_conversation_service)):
    return service.get(conversation_id)


@router.delete('/{conversation_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete(conversation_id: str, service=Depends(get_conversation_service)):
    service.delete(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
