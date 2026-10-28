import type {ReactNode} from 'react';
export function LoginView({hero,actions,feedback}:{hero:ReactNode;actions:ReactNode;feedback?:ReactNode}) {
 return <section className="mori-login"><div className="mori-wordmark" aria-label="mori">mori</div><h1>사진에 담긴 순간을<br/>한 권의 추억으로</h1><p className="mori-login-subtitle">사진과 한 문장으로 만드는 나만의 사진첩</p><div className="mori-login-hero">{hero}</div><p className="mori-memory-caption">그날의 바람이 아직도 선명하다.</p><div className="mori-login-actions">{actions}</div><p className="mori-login-policy">사진 처리 안내와 동의는 로그인 후 확인합니다.</p>{feedback && <div className="mori-login-feedback">{feedback}</div>}</section>;
}
