import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ResultsPage } from './ResultsPage';
import { routineFixture } from '../test/fixtures';

afterEach(cleanup);

it('offers a retry when a final result contains no routine steps', () => {
  const results = routineFixture();
  results.routine_steps = [];
  const retry = vi.fn();
  render(<ResultsPage results={results} onStartOver={retry} />);
  expect(screen.getByText('No routine steps were returned. Please try again.')).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Try Again' }));
  expect(retry).toHaveBeenCalledOnce();
});

it('shows explicit empty recommendations instead of permanent loading placeholders', () => {
  const results = routineFixture();
  results.routine_steps[0].ingredients = [];
  results.routine_steps[0].products = [];
  render(<ResultsPage results={results} onStartOver={vi.fn()} />);
  expect(screen.getByText('No ingredients were recommended for this step.')).toBeDefined();
  expect(screen.getByText('No products matched the selected ingredients and applied constraints for this step.')).toBeDefined();
  expect(screen.queryByText(/Loading|Finding products|Selecting ingredients/i)).toBeNull();
});

it('selecting a step displays its products and retry remains available', () => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  const restart = vi.fn();
  render(<ResultsPage results={routineFixture()} onStartOver={restart} />);
  const navigation = screen.getByRole('navigation', { name: 'Routine steps' });
  fireEvent.click(within(navigation).getByRole('button', { name: /Sunscreen/ }));
  expect(screen.getByRole('heading', { name: 'Sunscreen', level: 2 })).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'New Analysis' }));
  expect(restart).toHaveBeenCalledOnce();
});
