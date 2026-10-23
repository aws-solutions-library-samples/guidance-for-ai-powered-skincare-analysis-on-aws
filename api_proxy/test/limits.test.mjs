import test from 'node:test';
import assert from 'node:assert/strict';
import { UserLimits } from '../limits.mjs';

const config = { tableName: 'test-limits', requestsPerWindow: 5, windowSeconds: 3600, leaseSeconds: 1200 };
const cancelled = reasons => Object.assign(new Error('private'), {
  name: 'TransactionCanceledException', CancellationReasons: reasons.map(Code => ({ Code })),
});

test('counter and active lease share one idempotent transaction with an opaque identity key', async () => {
  const commands = [];
  const limits = new UserLimits({ send: async command => { commands.push(command); return {}; } }, config, () => 3700000);
  const lease = await limits.acquire('issuer\0private-subject', 'request-owner');
  const input = commands[0].input;
  assert.equal(input.ClientRequestToken, 'request-owner');
  assert.equal(input.TransactItems.length, 2);
  assert.ok(!JSON.stringify(input).includes('private-subject'));
  assert.equal(input.TransactItems[1].Put.Item.expires_at.N, '4900');
  assert.ok(input.TransactItems[1].Put.ConditionExpression.includes('expires_at <= :now'));
  assert.equal(lease.owner, 'request-owner');
  await limits.release(lease);
  assert.equal(commands[1].input.ExpressionAttributeValues[':owner'].S, 'request-owner');
  assert.ok(commands[1].input.ConditionExpression.includes('lease_owner'));
});

test('hourly exhaustion reports time to the next window', async () => {
  const limits = new UserLimits({ send: async () => { throw cancelled(['ConditionalCheckFailed', 'None']); } }, config, () => 3700000);
  await assert.rejects(limits.acquire('user', 'owner'), { code: 'USER_RATE_LIMITED', retryAfter: 3500 });
});

test('an active lease is distinct from the request quota', async () => {
  let calls = 0;
  const limits = new UserLimits({ send: async () => {
    if (++calls === 1) throw cancelled(['None', 'ConditionalCheckFailed']);
    return { Item: { expires_at: { N: '3750' } } };
  } }, config, () => 3700000);
  await assert.rejects(limits.acquire('user', 'owner'), { code: 'ANALYSIS_IN_PROGRESS', retryAfter: 50 });
});

test('transaction conflicts are not misreported as a user quota', async () => {
  const error = cancelled(['TransactionConflict', 'None']);
  const limits = new UserLimits({ send: async () => { throw error; } }, config);
  await assert.rejects(limits.acquire('user', 'owner'), value => value === error);
});

test('expired request cannot release a lease owned by its successor', async () => {
  const limits = new UserLimits({ send: async () => {
    throw Object.assign(new Error('owner changed'), { name: 'ConditionalCheckFailedException' });
  } }, config);
  await limits.release({ key: 'user-lease', owner: 'old-owner' });
});
