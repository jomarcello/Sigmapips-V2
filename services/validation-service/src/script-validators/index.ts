import axios from 'axios';

interface ValidationResponse {
  scriptName: string;
  status: 'success' | 'failed';
  details: {
    functionalityWorking: boolean;
    lastRunTime?: Date;
    errors?: string[];
  };
}

export async function validateSignalProcessor(): Promise<ValidationResponse> {
  try {
    // Test TradingView webhook ontvangst
    const webhookResponse = await axios.post('https://tradingview-signal-processor-production.up.railway.app/webhook', {
      symbol: 'BTCUSDT',
      interval: '1h',
      strategy: 'TEST_VALIDATION'
    });

    // Controleer of het signaal is doorgestuurd
    const signalId = webhookResponse.data.signalId;
    
    // Check of nieuws is gescrapet
    const newsResponse = await axios.get(`https://tradingview-signal-processor-production.up.railway.app/news/${signalId}`);
    
    return {
      scriptName: 'Signal Entry + News Scraper',
      status: 'success',
      details: {
        functionalityWorking: true,
        lastRunTime: new Date(),
      }
    };
  } catch (error) {
    return {
      scriptName: 'Signal Entry + News Scraper',
      status: 'failed',
      details: {
        functionalityWorking: false,
        errors: [(error as Error).message]
      }
    };
  }
}

export async function validateAISignalProcessor(): Promise<ValidationResponse> {
  try {
    // Test signaal verwerking
    const testSignal = {
      symbol: 'BTCUSDT',
      interval: '1h',
      strategy: 'TEST_VALIDATION'
    };

    const response = await axios.post('https://tradingview-signal-ai-service-production.up.railway.app/process-signal', testSignal);
    
    // Controleer of de AI output correct is geformatteerd
    const aiOutput = response.data;
    const isValidOutput = aiOutput.analysis && aiOutput.recommendation;

    return {
      scriptName: 'AI Signal Processor',
      status: isValidOutput ? 'success' : 'failed',
      details: {
        functionalityWorking: isValidOutput,
        lastRunTime: new Date()
      }
    };
  } catch (error) {
    return {
      scriptName: 'AI Signal Processor',
      status: 'failed',
      details: {
        functionalityWorking: false,
        errors: [(error as Error).message]
      }
    };
  }
}

export async function validateNewsProcessor(): Promise<ValidationResponse> {
  try {
    const testNews = {
      articles: [
        {
          title: "Test Article",
          content: "This is a test article for validation purposes."
        }
      ]
    };

    const response = await axios.post('https://tradingview-news-ai-service-production.up.railway.app/process-news', testNews);
    
    const isValidSummary = response.data.summary && response.data.sentiment;

    return {
      scriptName: 'AI News Processor',
      status: isValidSummary ? 'success' : 'failed',
      details: {
        functionalityWorking: isValidSummary,
        lastRunTime: new Date()
      }
    };
  } catch (error) {
    return {
      scriptName: 'AI News Processor',
      status: 'failed',
      details: {
        functionalityWorking: false,
        errors: [(error as Error).message]
      }
    };
  }
}

export async function validateChartService(): Promise<ValidationResponse> {
  try {
    const testRequest = {
      symbol: 'BTCUSDT',
      interval: '1h'
    };

    const response = await axios.post('https://tradingview-chart-service-production.up.railway.app/generate-chart', testRequest);
    
    const hasImage = response.data.imageUrl || response.data.image;

    return {
      scriptName: 'TradingView Chart Service',
      status: hasImage ? 'success' : 'failed',
      details: {
        functionalityWorking: hasImage,
        lastRunTime: new Date()
      }
    };
  } catch (error) {
    return {
      scriptName: 'TradingView Chart Service',
      status: 'failed',
      details: {
        functionalityWorking: false,
        errors: [(error as Error).message]
      }
    };
  }
}

export async function validateTelegramService(): Promise<ValidationResponse> {
  try {
    const testMessage = {
      chatId: 'TEST_CHAT_ID',
      message: 'Test validation message',
      type: 'validation'
    };

    const response = await axios.post('https://tradingview-telegram-service-production.up.railway.app/send', testMessage);
    
    return {
      scriptName: 'Telegram Send Service',
      status: 'success',
      details: {
        functionalityWorking: true,
        lastRunTime: new Date()
      }
    };
  } catch (error) {
    return {
      scriptName: 'Telegram Send Service',
      status: 'failed',
      details: {
        functionalityWorking: false,
        errors: [(error as Error).message]
      }
    };
  }
}

export async function validateSubscriberMatcher(): Promise<ValidationResponse> {
  try {
    const testSignal = {
      symbol: 'BTCUSDT',
      strategy: 'TEST_STRATEGY'
    };

    const response = await axios.post('https://sup-abase-subscriber-matcher-production.up.railway.app/match', testSignal);
    
    const hasSubscribers = Array.isArray(response.data.subscribers);

    return {
      scriptName: 'Subscriber Matcher',
      status: hasSubscribers ? 'success' : 'failed',
      details: {
        functionalityWorking: hasSubscribers,
        lastRunTime: new Date()
      }
    };
  } catch (error) {
    return {
      scriptName: 'Subscriber Matcher',
      status: 'failed',
      details: {
        functionalityWorking: false,
        errors: [(error as Error).message]
      }
    };
  }
} 