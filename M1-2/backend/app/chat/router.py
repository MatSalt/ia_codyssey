from fastapi import APIRouter, Depends
from ..dependencies import get_chat_gateway, get_conversation_repository, get_data_repository
from ..models import ChatRequest, ChatResponse
from ..ports import ChatGateway, ConversationRepository, DataRepository
from .service import ChatService

router = APIRouter(prefix='/api/chat', tags=['chat'])


def get_chat_service(
    data_repo: DataRepository = Depends(get_data_repository),
    conversations: ConversationRepository = Depends(get_conversation_repository),
    gateway: ChatGateway = Depends(get_chat_gateway),
) -> ChatService:
    return ChatService(data_repo, conversations, gateway)


@router.post('', response_model=ChatResponse)
def reply(request: ChatRequest, service: ChatService = Depends(get_chat_service)):
    return service.reply(request)
