import { createHash } from 'node:crypto';
import {
  DeleteItemCommand, GetItemCommand, TransactWriteItemsCommand,
} from '@aws-sdk/client-dynamodb';
import { PublicError } from './errors.mjs';

export class UserLimits {
  constructor(client, { tableName, requestsPerWindow, windowSeconds, leaseSeconds }, now = Date.now) {
    Object.assign(this, { client, tableName, requestsPerWindow, windowSeconds, leaseSeconds, now });
  }

  async acquire(identity, owner) {
    const now = Math.floor(this.now() / 1000);
    const user = createHash('sha256').update(identity).digest('hex');
    const window = Math.floor(now / this.windowSeconds);
    const resetAt = (window + 1) * this.windowSeconds;
    const leaseKey = `USER#${user}#ACTIVE`;
    const counterKey = `USER#${user}#WINDOW#${window}`;
    try {
      await this.client.send(new TransactWriteItemsCommand({
        ClientRequestToken: owner,
        TransactItems: [
          { Update: {
            TableName: this.tableName, Key: { pk: { S: counterKey } },
            UpdateExpression: 'SET expires_at = :expiry ADD request_count :one',
            ConditionExpression: 'attribute_not_exists(request_count) OR request_count < :limit',
            ExpressionAttributeValues: {
              ':expiry': { N: String(resetAt + 86400) }, ':one': { N: '1' },
              ':limit': { N: String(this.requestsPerWindow) },
            },
          } },
          { Put: {
            TableName: this.tableName,
            Item: {
              pk: { S: leaseKey }, lease_owner: { S: owner },
              expires_at: { N: String(now + this.leaseSeconds) },
            },
            // TTL deletion is asynchronous; expiry is checked synchronously.
            ConditionExpression: 'attribute_not_exists(pk) OR expires_at <= :now',
            ExpressionAttributeValues: { ':now': { N: String(now) } },
          } },
        ],
      }));
      return { key: leaseKey, owner };
    } catch (error) {
      if (error?.name !== 'TransactionCanceledException') throw error;
      const reasons = error.CancellationReasons ?? [];
      if (reasons[0]?.Code === 'ConditionalCheckFailed') {
        throw new PublicError('USER_RATE_LIMITED', resetAt - now);
      }
      if (reasons[1]?.Code === 'ConditionalCheckFailed') {
        const result = await this.client.send(new GetItemCommand({
          TableName: this.tableName, Key: { pk: { S: leaseKey } },
          ConsistentRead: true, ProjectionExpression: 'expires_at',
        }));
        const expiresAt = Number(result.Item?.expires_at?.N);
        throw new PublicError('ANALYSIS_IN_PROGRESS',
          Number.isFinite(expiresAt) ? Math.max(1, expiresAt - now) : this.leaseSeconds);
      }
      throw error;
    }
  }

  async release(lease) {
    try {
      await this.client.send(new DeleteItemCommand({
        TableName: this.tableName, Key: { pk: { S: lease.key } },
        ConditionExpression: 'lease_owner = :owner',
        ExpressionAttributeValues: { ':owner': { S: lease.owner } },
      }));
    } catch (error) {
      // An expired lease may have been replaced by another request.
      if (error?.name !== 'ConditionalCheckFailedException') throw error;
    }
  }
}
