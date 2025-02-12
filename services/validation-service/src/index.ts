import axios from 'axios';
import { Octokit } from '@octokit/rest';

interface ServiceConfig {
  name: string;
  githubRepo: string;
  railwayUrl: string;
  expectedEndpoints: string[];
}

interface ValidationResult {
  name: string;
  githubStatus: boolean;
  railwayStatus: boolean;
  endpointsStatus: Record<string, boolean>;
}

export class ValidationService {
  private octokit: Octokit;
  
  constructor(private githubToken: string) {
    this.octokit = new Octokit({ auth: githubToken });
  }

  async validateService(config: ServiceConfig): Promise<ValidationResult> {
    const results = {
      name: config.name,
      githubStatus: await this.checkGithubRepo(config.githubRepo),
      railwayStatus: await this.checkRailwayDeployment(config.railwayUrl),
      endpointsStatus: await this.checkEndpoints(config.railwayUrl, config.expectedEndpoints)
    };

    return results;
  }

  private async checkGithubRepo(repo: string): Promise<boolean> {
    try {
      await this.octokit.repos.get({
        owner: 'your-org',
        repo: repo
      });
      return true;
    } catch {
      return false;
    }
  }

  private async checkRailwayDeployment(url: string): Promise<boolean> {
    try {
      const response = await axios.get(`${url}/health`);
      return response.status === 200;
    } catch {
      return false;
    }
  }

  private async checkEndpoints(baseUrl: string, endpoints: string[]): Promise<Record<string, boolean>> {
    const results: Record<string, boolean> = {};
    
    for (const endpoint of endpoints) {
      try {
        const response = await axios.get(`${baseUrl}${endpoint}`);
        results[endpoint] = response.status === 200;
      } catch {
        results[endpoint] = false;
      }
    }
    
    return results;
  }
} 