import type {AuthProvider} from '../../api/types';

export function oauthProviders(value: unknown): AuthProvider[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((provider): provider is AuthProvider => provider === 'google' || provider === 'kakao'))];
}

export function oauthLoginUrl(provider: AuthProvider, returnTo = '/goods'): string {
  if (provider !== 'google' && provider !== 'kakao') throw new Error('Unsupported login provider');
  const albumPath = /^\/albums\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/(edit|progress|review|view)$/i;
  const designPath = /^\/designs\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const destination = ['/goods','/designs','/albums'].includes(returnTo) || albumPath.test(returnTo) || designPath.test(returnTo) ? returnTo : '/goods';
  return `/api/v1/auth/${provider}/start?return_to=${encodeURIComponent(destination)}`;
}

export function oauthErrorMessage(search: string): string {
  const error = new URLSearchParams(search).get('auth_error');
  if (error === 'failed') return '로그인하지 못했어요. 잠시 후 다시 시도해 주세요.';
  if (error === 'cancelled') return '로그인이 취소되었어요. 원하실 때 다시 로그인해 주세요.';
  return '';
}
