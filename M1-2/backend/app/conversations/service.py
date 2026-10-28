class ConversationService:
    def __init__(self, repo): self.repo = repo
    def create(self, payload): return self.repo.create(payload)
    def list_conversations(self): return self.repo.list_conversations()
    def get(self, conversation_id): return self.repo.get(conversation_id)
    def append_turn(self, conversation_id, question, answer):
        return self.repo.append_turn(conversation_id, question, answer)
    def delete(self, conversation_id): return self.repo.delete(conversation_id)
