import { ValidationService } from '../index';
import axios from 'axios';
import { Octokit } from '@octokit/rest';

jest.mock('axios');
jest.mock('@octokit/rest');

describe('ValidationService', () => {
  let validationService: ValidationService;
  
  beforeEach(() => {
    validationService = new ValidationService('test-token');
  });

  it('should check GitHub repo status', async () => {
    const mockGet = jest.fn().mockResolvedValue({ data: {} });
    (Octokit as jest.Mock).mockImplementation(() => ({
      repos: { get: mockGet }
    }));

    const result = await validationService.validateService({
      name: 'Test Service',
      githubRepo: 'test-repo',
      railwayUrl: 'http://test.url',
      expectedEndpoints: ['/test']
    });

    expect(result.githubStatus).toBe(true);
    expect(mockGet).toHaveBeenCalledWith({
      owner: 'your-org',
      repo: 'test-repo'
    });
  });

  it('should check Railway deployment status', async () => {
    (axios.get as jest.Mock).mockResolvedValueOnce({ status: 200 });

    const result = await validationService.validateService({
      name: 'Test Service',
      githubRepo: 'test-repo',
      railwayUrl: 'http://test.url',
      expectedEndpoints: ['/test']
    });

    expect(result.railwayStatus).toBe(true);
    expect(axios.get).toHaveBeenCalledWith('http://test.url/health');
  });
}); 