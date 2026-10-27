export function emitMetrics(event, values) {
  const deployment = process.env.METRICS_DEPLOYMENT;
  if (!deployment) return;
  console.log(JSON.stringify({
    _aws: {
      Timestamp: Date.now(),
      CloudWatchMetrics: [{
        Namespace: 'SmartBeauty/ExactSearch', Dimensions: [['Deployment']],
        Metrics: Object.keys(values).map(Name => ({ Name, Unit: 'Count' })),
      }],
    },
    Deployment: deployment, event, ...values,
  }));
}
