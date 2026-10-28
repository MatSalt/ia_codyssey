import secrets
from datetime import datetime, timezone, timedelta
from backend.auth import repository
from backend.http.errors import APIError
from backend.http.security import token_hash

NOTICE = ('사진은 크기 조정·압축 후 비공개 보관하며 AI 이미지 변환 및 글귀 생성에 사용합니다. 원본 파일의 별도 보관은 보장하지 않습니다. '
          '사진첩 삭제 시 접근을 차단하고 파일은 비동기로 삭제합니다. '
          '처리 중 장애 복구에 필요한 파일과 동의 이력은 정리 정책에 따라 보존될 수 있습니다. '
          '개발용 가짜 생성 모드에서는 실제 외부 AI를 호출하지 않습니다.')


async def login(factory, settings, account):
    raw = secrets.token_urlsafe(32)
    async with factory() as session, session.begin():
        user = await repository.synthetic_user(session, account)
        if user is None:
            raise APIError(401, 'AUTH_REQUIRED')
        await repository.save_session(session, user.id, token_hash(raw),
            datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds))
    return raw


async def me(factory, settings, context):
    async with factory() as session:
        user = await repository.user_by_id(session, context.user_id)
        consent = await repository.get_consent(session, context.user_id, settings.consent_policy_version)
        return {'user': {'id': str(user.id), 'display_name': user.display_name},
            'consent': {'required': consent is None, 'policy_version': settings.consent_policy_version, 'notice': NOTICE}}


async def consent(factory, settings, context, body):
    if body.policy_version != settings.consent_policy_version or not body.agreed:
        raise APIError(422, 'VALIDATION_ERROR')
    async with factory() as session, session.begin():
        row, created = await repository.agree(session, context.user_id, body.policy_version, body.purpose)
        return {'policy_version': row.policy_version, 'purpose': row.purpose,
                'agreed_at': row.agreed_at.isoformat().replace('+00:00', 'Z')}, created


async def logout(factory, context):
    async with factory() as session, session.begin():
        await repository.revoke(session, context.session_id)
