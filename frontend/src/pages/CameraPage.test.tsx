import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CameraPage } from './CameraPage';
import { analysisErrors } from '../utils/analysisErrors';

vi.mock('react-webcam', () => ({ default: () => <div>Camera preview</div> }));

let readers: FakeFileReader[];

class FakeFileReader {
  result: string | null = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readAsDataURL(file: File) {
    this.result = `data:image/jpeg;base64,${file.name}`;
    readers.push(this);
  }
}

class FakeImage {
  width = 2000;
  height = 1000;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  set src(_value: string) { this.onload?.(); }
}

beforeEach(() => {
  readers = [];
  vi.stubGlobal('FileReader', FakeFileReader);
  vi.stubGlobal('Image', FakeImage);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(),
  } as unknown as ReturnType<HTMLCanvasElement['getContext']>);
  let index = 0;
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation(() => `data:image/jpeg;base64,photo-${++index}`);
});
afterEach(cleanup);

async function mount() {
  const onComplete = vi.fn();
  await act(async () => { render(<CameraPage onComplete={onComplete} onCancel={vi.fn()} />); });
  return { input: screen.getByLabelText('Upload photos'), onComplete };
}

function upload(input: HTMLElement, count: number) {
  fireEvent.change(input, {
    target: { files: Array.from({ length: count }, (_, index) => new File(['image'], `${index}.jpg`, { type: 'image/jpeg' })) },
  });
}

async function finishConversions() {
  await act(async () => { readers.splice(0).forEach(reader => reader.onload?.()); });
}

it('caps concurrent selections at three photos and keeps Analyze usable', async () => {
  const { input, onComplete } = await mount();
  upload(input, 2);
  upload(input, 2);
  expect(readers).toHaveLength(4);
  expect((screen.getByRole('button', { name: 'Analyze' }) as HTMLButtonElement).disabled).toBe(true);
  await finishConversions();
  expect(screen.getByText('3/3 Photos')).toBeDefined();
  expect(screen.getAllByAltText(/Captured \d/)).toHaveLength(3);
  fireEvent.click(screen.getByRole('button', { name: 'Analyze' }));
  expect(onComplete).toHaveBeenCalledOnce();
  expect(onComplete.mock.calls[0][0]).toHaveLength(3);
});

it('reset during conversion discards those photos and permits a new selection', async () => {
  const { input, onComplete } = await mount();
  upload(input, 2);
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
  await finishConversions();
  expect(screen.getByText('0/3 Photos')).toBeDefined();
  upload(input, 3);
  await finishConversions();
  fireEvent.click(screen.getByRole('button', { name: 'Analyze' }));
  expect(onComplete.mock.calls[0][0]).toHaveLength(3);
});

it('shows a file conversion failure and recovers on a later upload', async () => {
  const { input, onComplete } = await mount();
  upload(input, 1);
  await act(async () => { readers.shift()?.onerror?.(); });
  expect(screen.getByRole('alert').textContent).toMatch(/read|image/i);
  expect(screen.getByText('0/3 Photos')).toBeDefined();
  upload(input, 3);
  await finishConversions();
  expect(screen.queryByRole('alert')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Analyze' }));
  expect(onComplete).toHaveBeenCalledOnce();
});

it('ignores non-image files without attempting conversion', async () => {
  const { input } = await mount();
  fireEvent.change(input, { target: { files: [new File(['text'], 'notes.txt', { type: 'text/plain' })] } });
  expect(readers).toEqual([]);
  expect(screen.getByText('0/3 Photos')).toBeDefined();
});

it('shows a safety block, its code, and a support reference in an accessible alert', () => {
  render(<CameraPage onComplete={vi.fn()} onCancel={vi.fn()}
    error={analysisErrors.GUARDRAIL_PROMPT_ATTACK.message}
    errorCode="GUARDRAIL_PROMPT_ATTACK" requestId="request-123" />);
  const alert = screen.getByRole('alert');
  expect(alert.textContent).toContain('Analysis blocked by a safety check');
  expect(alert.textContent).toContain('GUARDRAIL_PROMPT_ATTACK');
  expect(alert.textContent).toContain('Reference: request-123');
});

it('offers sign-in recovery for an expired session', () => {
  const onSignIn = vi.fn();
  render(<CameraPage onComplete={vi.fn()} onCancel={vi.fn()} onSignIn={onSignIn}
    error={analysisErrors.AUTH_REQUIRED.message} errorCode="AUTH_REQUIRED" />);
  fireEvent.click(screen.getByRole('button', { name: 'Sign in again' }));
  expect(onSignIn).toHaveBeenCalledOnce();
});
