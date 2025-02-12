import { Test } from '@nestjs/testing';
import { SignalController } from '../src/signal.controller';

describe('SignalController', () => {
  let controller: SignalController;

  beforeEach(async () => {
    const module = await Test.createTestingModule({
      controllers: [SignalController],
    }).compile();

    controller = module.get(SignalController);
  });

  it('should process signals correctly', async () => {
    // Implementeer je tests
  });
}); 