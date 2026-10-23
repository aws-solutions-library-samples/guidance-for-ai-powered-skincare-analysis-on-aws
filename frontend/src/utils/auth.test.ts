import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { getAuthState, getIdToken, signIn, signOut } from './auth';

const sdk = vi.hoisted(() => ({
  authenticate: vi.fn(), complete: vi.fn(),
}));

vi.mock('amazon-cognito-identity-js', () => ({
  CognitoUserPool: class {},
  AuthenticationDetails: class {},
  CognitoUser: class {
    authenticateUser(_details: unknown, callbacks: unknown) { sdk.authenticate(callbacks); }
    completeNewPasswordChallenge(password: string, attributes: unknown, callbacks: unknown) {
      sdk.complete(password, attributes, callbacks);
    }
  },
}));

beforeEach(() => {
  vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'test-pool');
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'test-client');
  sdk.authenticate.mockReset();
  sdk.complete.mockReset();
  sdk.authenticate.mockImplementation(callbacks => callbacks.newPasswordRequired({ email_verified: 'true' }, []));
  sdk.complete.mockImplementation((_password, _attributes, callbacks) =>
    callbacks.onSuccess({ getIdToken: () => ({ getJwtToken: () => 'test-token' }) }));
});
afterEach(() => vi.unstubAllEnvs());

it('boots without Cognito configuration and explains why sign-in is unavailable', async () => {
  vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '');
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', '');
  const fetch = vi.fn(() => { throw new Error('No network expected'); });
  vi.stubGlobal('fetch', fetch);
  expect(await getAuthState()).toEqual({ isAuthenticated: false, email: null, idToken: null });
  expect(await getIdToken()).toBeNull();
  expect(() => signOut()).not.toThrow();
  await expect(signIn('test@example.invalid', 'unused')).rejects.toMatchObject({ code: 'AUTH_NOT_CONFIGURED' });
  expect(fetch).not.toHaveBeenCalled();
});

it('waits for a new password instead of reusing the temporary credential', async () => {
  const result = await signIn('test@example.invalid', 'Temporary123!');
  expect(result.status).toBe('new_password_required');
  expect(sdk.complete).not.toHaveBeenCalled();
  if (result.status !== 'new_password_required') throw new Error('Expected challenge');
  await expect(result.complete('Temporary123!')).rejects.toMatchObject({ code: 'AUTH_PASSWORD_REUSED' });
  expect(sdk.complete).not.toHaveBeenCalled();
  await expect(result.complete('MyNewPassword123!')).resolves.toBe('test-token');
  expect(sdk.complete.mock.calls[0][0]).toBe('MyNewPassword123!');
  expect(sdk.complete.mock.calls[0][1]).toEqual({});
});

it('passes only required writable attributes when completing a challenge', async () => {
  sdk.authenticate.mockImplementation(callbacks =>
    callbacks.newPasswordRequired({ email: 'test@example.invalid', email_verified: 'true' }, ['email']));
  const result = await signIn('test@example.invalid', 'Temporary123!');
  if (result.status !== 'new_password_required') throw new Error('Expected challenge');
  await result.complete('Different123!');
  expect(sdk.complete.mock.calls[0][1]).toEqual({ email: 'test@example.invalid' });
});

it('keeps password policy failures safe and allows the challenge to be retried', async () => {
  sdk.complete.mockImplementationOnce((_password, _attributes, callbacks) =>
    callbacks.onFailure(Object.assign(new Error('Internal pool details'), { name: 'InvalidPasswordException' })));
  const result = await signIn('test@example.invalid', 'Temporary123!');
  if (result.status !== 'new_password_required') throw new Error('Expected challenge');
  await expect(result.complete('short')).rejects.toMatchObject({ code: 'AUTH_PASSWORD_POLICY' });
  await expect(result.complete('Different123!')).resolves.toBe('test-token');
});

it('returns the signed-in result for an established user', async () => {
  sdk.authenticate.mockImplementation(callbacks =>
    callbacks.onSuccess({ getIdToken: () => ({ getJwtToken: () => 'test-token' }) }));
  await expect(signIn('test@example.invalid', 'Password123!')).resolves.toEqual({ status: 'signed_in', idToken: 'test-token' });
});

it('does not expose provider details in sign-in failures', async () => {
  sdk.authenticate.mockImplementation(callbacks =>
    callbacks.onFailure(Object.assign(new Error('private account details'), { name: 'NotAuthorizedException' })));
  const attempt = signIn('test@example.invalid', 'Password123!');
  await expect(attempt).rejects.toMatchObject({ code: 'AUTH_INVALID_CREDENTIALS' });
  await expect(attempt).rejects.not.toThrow('private');
});
