import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from '@aws-sdk/client-bedrock-agentcore';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { createHandler } from './handler.mjs';
import { UserLimits } from './limits.mjs';

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing configuration: ${name}`);
  return value;
}
function positiveInteger(name) {
  const value = Number(required(name));
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`Invalid configuration: ${name}`);
  return value;
}

// Never automatically replay a potentially accepted model invocation.
const runtime = new BedrockAgentCoreClient({ maxAttempts: 1 });
const limits = new UserLimits(new DynamoDBClient({ maxAttempts: 3 }), {
  tableName: required('LIMITS_TABLE_NAME'),
  requestsPerWindow: positiveInteger('USER_REQUESTS_PER_WINDOW'),
  windowSeconds: positiveInteger('USER_WINDOW_SECONDS'),
  leaseSeconds: positiveInteger('USER_LEASE_SECONDS'),
});
export const handler = awslambda.streamifyResponse(createHandler({
  invoke: (input, abortSignal) => runtime.send(new InvokeAgentRuntimeCommand(input), { abortSignal }),
  limits,
  wrapResponse: (stream, metadata) => awslambda.HttpResponseStream.from(stream, metadata),
  config: {
    apiId: required('API_ID'), issuer: required('COGNITO_ISSUER'),
    clientId: required('COGNITO_CLIENT_ID'), runtimeArn: required('AGENT_RUNTIME_ARN'),
  },
}));
