import { Controller } from '@nestjs/common';
import { EventPattern } from '@nestjs/microservices';
import { MessageBroker } from '../../../shared/message-broker';

@Controller()
export class SignalController {
  private messageBroker: MessageBroker;

  constructor() {
    this.messageBroker = new MessageBroker();
    this.messageBroker.connect();
  }

  @EventPattern('trading.signal')
  async handleSignal(data: any) {
    try {
      // Verwerk het signaal
      const processedSignal = await this.processSignal(data);
      
      // Publiceer het verwerkte signaal
      await this.messageBroker.publishEvent(
        'signals',
        'signal.processed',
        processedSignal
      );
    } catch (error) {
      console.error('Error processing signal:', error);
    }
  }

  private async processSignal(data: any) {
    // Implementeer je signaalverwerkingslogica hier
    return data;
  }
} 