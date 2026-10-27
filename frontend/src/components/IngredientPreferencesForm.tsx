import { useEffect, useRef, useState } from 'react';
import { ApiService } from '../utils/api';
import { API_CONFIG } from '../config/constants';
import { formatMinorUnits, parseMinorUnits } from '../utils/money';
import type { IngredientLookupResult, IngredientOption, PreferenceDraft } from '../types';

interface Props {
  value: PreferenceDraft;
  onChange: (draft: PreferenceDraft) => void;
  onValidityChange: (valid: boolean) => void;
}

export function IngredientPreferencesForm({ value, onChange, onValidityChange }: Props) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<IngredientLookupResult>();
  const [category, setCategory] = useState('');
  const [intent, setIntent] = useState<'exclude' | 'require'>('exclude');
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [priceNeedsReview, setPriceNeedsReview] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController>();
  const preferences = value.preferences;
  const excluded = preferences.excluded_ingredient_ids ?? [];
  const required = preferences.must_have_by_category ?? [];
  const requiredCount = required.reduce((sum, item) => sum + item.ingredient_ids.length, 0);
  const currency = preferences.currency ?? options?.default_currency ?? '';
  const digits = options?.currency_minor_units[currency];
  const priceValid = !priceNeedsReview && (price === '' || (digits !== undefined && parseMinorUnits(price, digits) !== undefined));
  const configurationValid = !options || (
    (!preferences.currency || options.supported_currencies.includes(preferences.currency))
    && (!preferences.market || options.supported_markets.includes(preferences.market))
    && required.every(entry => options.categories.includes(entry.category_id))
  );

  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    onValidityChange(!busy && !name.trim() && priceValid && configurationValid);
  }, [busy, name, priceValid, configurationValid, onValidityChange]);

  function loadOptions(result: IngredientLookupResult) {
    setOptions(result);
    setCategory(result.categories[0] ?? '');
    if (preferences.max_price_minor != null) {
      const selectedCurrency = preferences.currency ?? result.default_currency ?? '';
      const precision = result.currency_minor_units[selectedCurrency];
      if (precision === undefined) {
        setPrice(''); setPriceNeedsReview(true);
      } else {
        setPrice(formatMinorUnits(preferences.max_price_minor, precision));
        setPriceNeedsReview(false);
      }
    }
  }

  async function lookup(input: Parameters<ApiService['lookupIngredients']>[0]) {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError('');
    try {
      const result = await new ApiService(API_CONFIG.DEFAULT_URL).lookupIngredients(input, controller.signal);
      if (!controller.signal.aborted && active.current === controller) return result;
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Could not look up ingredients.');
    } finally {
      if (active.current === controller) { active.current = undefined; setBusy(false); }
    }
  }

  async function expand() {
    setOpen(!open);
    if (!open && !options) {
      const result = await lookup({});
      if (result) loadOptions(result);
    }
  }

  function add(option: IngredientOption) {
    setName(option.display_name);
    const id = option.ingredient_id;
    if (intent === 'exclude') {
      if (required.some(entry => entry.ingredient_ids.includes(id))) {
        setError('Remove this ingredient from must-haves before excluding it.');
        return;
      }
      if (!excluded.includes(id) && excluded.length >= 20) { setError('Choose up to 20 exclusions.'); return; }
      onChange({
        labels: { ...value.labels, [id]: option.display_name },
        preferences: { ...preferences, excluded_ingredient_ids: [...new Set([...excluded, id])] },
      });
    } else {
      if (!category) { setError('Choose a category for this must-have.'); return; }
      if (excluded.includes(id)) { setError('Remove this ingredient from exclusions before making it mandatory.'); return; }
      const previous = required.find(entry => entry.category_id === category);
      if (!previous?.ingredient_ids.includes(id) && (requiredCount >= 20 || (!previous && required.length >= 8))) {
        setError('Choose up to 20 must-haves across eight categories.'); return;
      }
      const next = required.filter(entry => entry.category_id !== category);
      next.push({ category_id: category, ingredient_ids: [...new Set([...(previous?.ingredient_ids ?? []), id])] });
      onChange({ labels: { ...value.labels, [id]: option.display_name }, preferences: { ...preferences, must_have_by_category: next } });
    }
    setName('');
    setError('');
  }

  async function find() {
    const result = await lookup({ references: [{ name: name.trim() }] });
    const match = result?.results?.[0];
    if (match?.status === 'resolved') add(match);
    else if (match) setError(match.status === 'ambiguous'
      ? 'This name has more than one identity. Enter a more specific ingredient name.'
      : 'No exact ingredient identity was found. Check the name or clear it to continue.');
  }

  function remove(id: string, requiredCategory?: string) {
    onChange({ ...value, preferences: requiredCategory ? {
      ...preferences,
      must_have_by_category: required.map(entry => entry.category_id === requiredCategory
        ? { ...entry, ingredient_ids: entry.ingredient_ids.filter(item => item !== id) } : entry)
        .filter(entry => entry.ingredient_ids.length),
    } : { ...preferences, excluded_ingredient_ids: excluded.filter(item => item !== id) } });
  }

  const inputClass = 'block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm';
  return (
    <section className="rounded-2xl bg-white/95 p-4 shadow-sm border border-gray-200">
      <button type="button" onClick={() => void expand()} aria-expanded={open} className="w-full text-left font-semibold text-gray-800">
        Ingredient preferences (optional)
        <span className="block font-normal text-sm text-gray-500 mt-1">
          {excluded.length || requiredCount ? `${excluded.length} exclusions · ${requiredCount} must-haves` : 'Set exact exclusions, category must-haves, or a price limit.'}
        </span>
        {(name.trim() || !priceValid || !configurationValid) && <span className="block text-sm text-amber-800 mt-1">Finish editing or clear your preferences to continue.</span>}
      </button>
      {open && (
        <div className="mt-4 space-y-4">
          <p className="text-sm text-gray-600">Products rank by exact ingredient matches. Every explicit must-have is required for its category. Exclusions apply to every step.</p>
          {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
          {!configurationValid && <p role="alert" className="text-sm text-red-700">A saved currency, market, or category is no longer supported. Update or remove that preference to continue.</p>}
          {priceNeedsReview && <p role="alert" className="text-sm text-red-700">Choose a supported currency and re-enter your saved price limit, or clear all preferences.</p>}
          {busy && <p role="status" className="text-sm text-gray-500">Looking up ingredient options…</p>}
          {!options && !busy && <button type="button" className="underline text-sm" onClick={() => void lookup({}).then(result => {
            if (result) loadOptions(result);
          })}>Retry ingredient lookup</button>}
          {options && (
            <>
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="text-sm">Preference
                  <select className={inputClass} value={intent} disabled={busy} onChange={event => setIntent(event.target.value as 'exclude' | 'require')}>
                    <option value="exclude">Exclude from all products</option><option value="require">Must have in a category</option>
                  </select>
                </label>
                <label className="text-sm">Product category
                  <select className={inputClass} value={category} disabled={busy} onChange={event => {
                    setCategory(event.target.value);
                    setOptions({ ...options, ingredients: undefined, as_of: undefined });
                  }}>
                    {options.categories.map(item => <option key={item}>{item}</option>)}
                  </select>
                </label>
              </div>
              <div className="flex flex-wrap gap-2 items-end">
                <label className="text-sm flex-1 min-w-48">Exact ingredient name
                  <input className={inputClass} value={name} maxLength={256} disabled={busy} onChange={event => { setName(event.target.value); setError(''); }}
                    onKeyDown={event => { if (event.key === 'Enter' && name.trim()) { event.preventDefault(); void find(); } }} />
                </label>
                <button type="button" disabled={busy || !name.trim()} onClick={() => void find()} className="rounded-lg bg-[#8B9D83] px-3 py-2 text-white text-sm disabled:opacity-50">Find and add</button>
                {name && <button type="button" onClick={() => {
                  active.current?.abort(); active.current = undefined; setBusy(false); setName(''); setError('');
                }} className="text-sm underline">Clear name</button>}
              </div>
              <button type="button" disabled={busy} className="text-sm underline" onClick={() => void lookup({ category_id: category }).then(result => {
                if (result) setOptions(result);
              })}>Browse common ingredients for {category}</button>
              {!!options.ingredients?.length && (
                <label className="block text-sm">Common ingredients (advisory)
                  <select className={inputClass} value="" disabled={busy} onChange={event => {
                    const option = options.ingredients?.find(item => item.ingredient_id === event.target.value);
                    if (option) add(option);
                  }}>
                    <option value="">Choose an ingredient</option>
                    {options.ingredients.map(item => <option value={item.ingredient_id} key={item.ingredient_id}>{item.display_name}</option>)}
                  </select>
                </label>
              )}
              {options.ingredients?.length === 0 && <p className="text-sm text-gray-600">No common-ingredient summary is available. You can still look up an exact ingredient name.</p>}
              <div className="grid sm:grid-cols-3 gap-3">
                <label className="text-sm">Market
                  <select className={inputClass} disabled={busy} value={preferences.market ?? ''} onChange={event => onChange({ ...value, preferences: { ...preferences, market: event.target.value || null } })}>
                    {preferences.market && !options.supported_markets.includes(preferences.market) && <option disabled value={preferences.market}>{preferences.market} (unavailable)</option>}
                    <option value="">Catalog default{options.default_market ? ` (${options.default_market})` : ''}</option>{options.supported_markets.map(item => <option key={item}>{item}</option>)}
                  </select>
                </label>
                <label className="text-sm">Currency
                  <select className={inputClass} disabled={busy} value={currency} onChange={event => {
                    const nextCurrency = event.target.value;
                    const amount = parseMinorUnits(price, options.currency_minor_units[nextCurrency]);
                    onChange({ ...value, preferences: {
                      ...preferences, currency: nextCurrency || null,
                      ...(!priceNeedsReview && amount !== undefined ? { max_price_minor: amount } : {}),
                    } });
                  }}>
                    {currency && !options.supported_currencies.includes(currency) && <option disabled value={currency}>{currency} (unavailable)</option>}
                    {options.supported_currencies.map(item => <option key={item}>{item}</option>)}
                  </select>
                </label>
                <label className="text-sm">Maximum price per product
                  <input className={inputClass} disabled={busy || digits === undefined} maxLength={32} inputMode="decimal" value={price} aria-invalid={!priceValid} placeholder="No limit"
                    onChange={event => {
                      const raw = event.target.value; setPrice(raw);
                      const amount = digits === undefined ? undefined : parseMinorUnits(raw, digits);
                      if (amount !== undefined) {
                        setPriceNeedsReview(false);
                        onChange({
                          ...value, preferences: { ...preferences,
                            currency: preferences.currency ?? options.default_currency,
                            max_price_minor: amount,
                          },
                        });
                      }
                    }} />
                </label>
              </div>
              {!priceValid && <p role="alert" className="text-sm text-red-700">Enter a nonnegative price{digits ? ` with up to ${digits} decimal places` : ' in whole units'}.</p>}
            </>
          )}
          {!!excluded.length && <div className="text-sm"><strong>Exclude from every step</strong><ul className="mt-2 space-y-1">
            {excluded.map(id => <li key={id}>{value.labels[id] ?? 'Selected ingredient'} <button type="button" disabled={busy} className="underline ml-2" aria-label={`Remove exclusion ${value.labels[id] ?? 'ingredient'}`} onClick={() => remove(id)}>Remove</button></li>)}
          </ul></div>}
          {required.map(entry => <div className="text-sm" key={entry.category_id}><strong>Must have in {entry.category_id}</strong><ul className="mt-2 space-y-1">
            {entry.ingredient_ids.map(id => <li key={id}>{value.labels[id] ?? 'Selected ingredient'} <button type="button" disabled={busy} className="underline ml-2" aria-label={`Remove ${value.labels[id] ?? 'ingredient'} from ${entry.category_id}`} onClick={() => remove(id, entry.category_id)}>Remove</button></li>)}
          </ul></div>)}
          <button type="button" className="text-sm underline" onClick={() => {
            active.current?.abort(); active.current = undefined; setBusy(false); setName(''); setPrice(''); setPriceNeedsReview(false); setError('');
            onChange({ preferences: {}, labels: {} });
          }}>Clear all preferences</button>
        </div>
      )}
    </section>
  );
}
