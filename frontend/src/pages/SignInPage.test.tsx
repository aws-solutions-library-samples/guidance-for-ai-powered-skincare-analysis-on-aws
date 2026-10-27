import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { signIn } from '../utils/auth';
import { SignInPage } from './SignInPage';

vi.mock('../utils/auth', async () => {
  const actual = await vi.importActual<typeof import('../utils/auth')>('../utils/auth');
  return { ...actual, signIn: vi.fn() };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('requires matching new passwords before completing the Cognito challenge', async () => {
  const complete = vi.fn().mockResolvedValue('test-token');
  vi.mocked(signIn).mockResolvedValue({ status: 'new_password_required', complete });
  const success = vi.fn();
  render(<SignInPage onSuccess={success} onBack={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'test@example.invalid' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Temporary123!' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Sign In' })); });
  expect(screen.queryByLabelText('Password')).toBeNull();
  expect(success).not.toHaveBeenCalled();
  expect(complete).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'Different123!' } });
  fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: 'Mismatch123!' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Set Password and Sign In' })); });
  expect(screen.getByRole('alert').textContent).toContain('AUTH_PASSWORD_MISMATCH');
  expect(complete).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: 'Different123!' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Set Password and Sign In' })); });
  expect(complete).toHaveBeenCalledWith('Different123!');
  expect(success).toHaveBeenCalledOnce();
});
