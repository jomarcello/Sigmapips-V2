import axios from 'axios';

export async function testCompleteDataFlow() {
  try {
    // 1. Simuleer een TradingView signaal
    const signalResponse = await axios.post('signal-entry-url/webhook', {
      symbol: 'BTCUSDT',
      interval: '1h',
      strategy: 'TEST'
    });

    // 2. Volg het signaal door het systeem
    const signalId = signalResponse.data.signalId;
    
    // 3. Wacht en controleer verschillende endpoints
    await Promise.all([
      checkAIProcessing(signalId),
      checkNewsProcessing(signalId),
      checkTelegramDelivery(signalId)
    ]);

    return true;
  } catch (error) {
    console.error('Dataflow test failed:', error);
    return false;
  }
}

async function checkAIProcessing(signalId: string): Promise<boolean> {
  try {
    const response = await axios.get(`${process.env.AI_SERVICE_URL}/status/${signalId}`);
    return response.data.status === 'completed';
  } catch {
    return false;
  }
}

async function checkNewsProcessing(signalId: string): Promise<boolean> {
  try {
    const response = await axios.get(`${process.env.NEWS_SERVICE_URL}/status/${signalId}`);
    return response.data.status === 'completed';
  } catch {
    return false;
  }
}

async function checkTelegramDelivery(signalId: string): Promise<boolean> {
  try {
    const response = await axios.get(`${process.env.TELEGRAM_SERVICE_URL}/delivery/${signalId}`);
    return response.data.delivered === true;
  } catch {
    return false;
  }
} 