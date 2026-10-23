/**
 * Cognito authentication utility.
 *
 * Uses direct auth (username/password) for admin-created Cognito User Pool users.
 */
import {
    CognitoUserPool,
    CognitoUser,
    AuthenticationDetails,
    CognitoUserSession,
} from 'amazon-cognito-identity-js';

let userPool: CognitoUserPool | undefined;

function getUserPool(): CognitoUserPool | undefined {
    const UserPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID;
    const ClientId = import.meta.env.VITE_COGNITO_CLIENT_ID;
    if (!UserPoolId || !ClientId) return undefined;
    userPool ??= new CognitoUserPool({ UserPoolId, ClientId });
    return userPool;
}

export interface AuthState {
    isAuthenticated: boolean;
    email: string | null;
    idToken: string | null;
}

const authMessages = {
    AUTH_INVALID_CREDENTIALS: 'The email or password is incorrect. Please try again.',
    AUTH_PASSWORD_POLICY: 'Choose a password that meets the account password requirements.',
    AUTH_PASSWORD_REUSED: 'Choose a new password that is different from your temporary password.',
    AUTH_PASSWORD_MISMATCH: 'The new passwords do not match.',
    AUTH_RATE_LIMITED: 'Too many sign-in attempts. Please wait a minute and try again.',
    AUTH_ACCOUNT_SETUP: 'Your account needs setup or a password reset. Please contact the administrator.',
    AUTH_NOT_CONFIGURED: 'Sign-in is not configured. Please contact the administrator.',
    AUTH_FAILED: 'Sign-in could not complete. Please try again.',
} as const;

export class AuthError extends Error {
    constructor(readonly code: keyof typeof authMessages) {
        super(authMessages[code]);
        this.name = 'AuthError';
    }
}

export function safeAuthError(error: unknown): AuthError {
    if (error instanceof AuthError) return error;
    const name = error instanceof Error ? error.name : '';
    if (name === 'NotAuthorizedException' || name === 'UserNotFoundException') return new AuthError('AUTH_INVALID_CREDENTIALS');
    if (name === 'InvalidPasswordException' || name === 'PasswordHistoryPolicyViolationException') return new AuthError('AUTH_PASSWORD_POLICY');
    if (name === 'TooManyRequestsException' || name === 'LimitExceededException') return new AuthError('AUTH_RATE_LIMITED');
    if (name === 'UserNotConfirmedException' || name === 'PasswordResetRequiredException') return new AuthError('AUTH_ACCOUNT_SETUP');
    return new AuthError('AUTH_FAILED');
}

export interface NewPasswordChallenge {
    status: 'new_password_required';
    complete: (newPassword: string) => Promise<string>;
}

export type SignInResult = { status: 'signed_in'; idToken: string } | NewPasswordChallenge;

/** Get the current session's ID token, or null if not authenticated. */
export function getIdToken(): Promise<string | null> {
    return new Promise((resolve) => {
        const user = getUserPool()?.getCurrentUser();
        if (!user) {
            resolve(null);
            return;
        }
        user.getSession((err: Error | null, session: CognitoUserSession | null) => {
            if (err || !session?.isValid()) {
                resolve(null);
                return;
            }
            resolve(session.getIdToken().getJwtToken());
        });
    });
}

/** Check current auth state. */
export function getAuthState(): Promise<AuthState> {
    return new Promise((resolve) => {
        const user = getUserPool()?.getCurrentUser();
        if (!user) {
            resolve({ isAuthenticated: false, email: null, idToken: null });
            return;
        }
        user.getSession((err: Error | null, session: CognitoUserSession | null) => {
            if (err || !session?.isValid()) {
                resolve({ isAuthenticated: false, email: null, idToken: null });
                return;
            }
            const payload = session.getIdToken().decodePayload();
            resolve({
                isAuthenticated: true,
                email: (payload['email'] as string) || null,
                idToken: session.getIdToken().getJwtToken(),
            });
        });
    });
}

/** Sign in, or return a challenge that requires an explicit new password. */
export function signIn(email: string, password: string): Promise<SignInResult> {
    return new Promise((resolve, reject) => {
        const pool = getUserPool();
        if (!pool) {
            reject(new AuthError('AUTH_NOT_CONFIGURED'));
            return;
        }
        const user = new CognitoUser({ Username: email, Pool: pool });
        const authDetails = new AuthenticationDetails({
            Username: email,
            Password: password,
        });
        user.authenticateUser(authDetails, {
            onSuccess: (session: CognitoUserSession) => {
                resolve({ status: 'signed_in', idToken: session.getIdToken().getJwtToken() });
            },
            onFailure: (err: Error) => {
                reject(safeAuthError(err));
            },
            newPasswordRequired: (attributes: Record<string, unknown>, required: string[]) => {
                const requiredAttributes: Record<string, string> = {};
                for (const name of required) {
                    if (typeof attributes[name] !== 'string' || !attributes[name]) {
                        reject(new AuthError('AUTH_ACCOUNT_SETUP'));
                        return;
                    }
                    requiredAttributes[name] = attributes[name] as string;
                }
                resolve({
                    status: 'new_password_required',
                    complete: (newPassword: string) => new Promise((finish, fail) => {
                        if (!newPassword || newPassword === password) {
                            fail(new AuthError('AUTH_PASSWORD_REUSED'));
                            return;
                        }
                        user.completeNewPasswordChallenge(newPassword, requiredAttributes, {
                            onSuccess: (session: CognitoUserSession) => finish(session.getIdToken().getJwtToken()),
                            onFailure: (err: Error) => fail(safeAuthError(err)),
                        });
                    }),
                });
            },
        });
    });
}

/** Sign out the current user. */
export function signOut(): void {
    const user = getUserPool()?.getCurrentUser();
    if (user) {
        user.signOut();
    }
}
