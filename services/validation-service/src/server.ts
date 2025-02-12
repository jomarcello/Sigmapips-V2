import express from 'express';
import dotenv from 'dotenv';
import { ValidationService } from './index';
import { serviceConfigs } from './config';
import { testCompleteDataFlow } from './dataflow-test';
import {
  validateSignalProcessor,
  validateAISignalProcessor,
  validateNewsProcessor,
  validateChartService,
  validateTelegramService,
  validateSubscriberMatcher
} from './script-validators';

dotenv.config();

const app = express();
const port = process.env.PORT || 3000;

const validationService = new ValidationService(process.env.GITHUB_TOKEN!);

app.get('/health', (req, res) => {
  res.json({ status: 'healthy' });
});

app.get('/validate-all', async (req, res) => {
  try {
    const results = await Promise.all(
      serviceConfigs.map(config => validationService.validateService(config))
    );
    res.json({ results });
  } catch (error) {
    res.status(500).json({ error: 'Validation failed' });
  }
});

app.get('/test-dataflow', async (req, res) => {
  try {
    const result = await testCompleteDataFlow();
    res.json({ success: result });
  } catch (error) {
    res.status(500).json({ error: 'Dataflow test failed' });
  }
});

app.get('/validate-scripts', async (req, res) => {
  try {
    const results = await Promise.all([
      validateSignalProcessor(),
      validateAISignalProcessor(),
      validateNewsProcessor(),
      validateChartService(),
      validateTelegramService(),
      validateSubscriberMatcher()
    ]);

    const allSuccess = results.every(result => result.status === 'success');

    res.json({
      overallStatus: allSuccess ? 'success' : 'failed',
      results
    });
  } catch (error) {
    res.status(500).json({
      overallStatus: 'error',
      error: (error as Error).message
    });
  }
});

app.listen(port, () => {
  console.log(`Validation service running on port ${port}`);
}); 