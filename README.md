# GitHub Repository Summarizer Using GitHub Copilot

A FastAPI service that analyzes GitHub repositories and generates human-readable summaries using Nebius Token Factory LLM.

## Features

- **Smart Repository Fetching**: Downloads repository metadata, README, configuration files, and sample source code from GitHub
- **Intelligent Content Filtering**: Automatically ignores binary files, lock files, and build artifacts
- **LLM-Powered Summaries**: Uses Nebius Token Factory API to generate meaningful summaries
- **Structured Output**: Returns summary, list of technologies, and project structure in a consistent format

## Setup Instructions

### Prerequisites

- Python 3.10 or higher
- Git (to clone the repository)
- A Nebius Token Factory API key (sign up at https://auth.api.nebius.ai/)

### Step 1: Clone and Navigate

```bash
cd /path/to/repo_summariser
```

### Step 2: Create a Virtual Environment

```bash
python3.10 -m venv venv
source venv/bin/activate  
```

### Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Set Environment Variables

You can set them for the current shell or place them in your shell startup file (`~/.zshrc`, `~/.bashrc`, etc.) so they’re applied automatically.

**Temporary (current session):**
```bash
export NEBIUS_API_KEY="your_nebius_api_key_here"

# Optional: GitHub token for higher API rate limits
export GITHUB_TOKEN="your_github_token_here"
```

**Persistently (add to `~/.zshrc`):**
```bash
# ~/.zshrc
export NEBIUS_API_KEY="your_nebius_api_key_here"
export GITHUB_TOKEN="your_github_token_here"
```
Then reload the file or open a new terminal:
```bash
source ~/.zshrc
```


### Step 5: Start the Server

```bash
uvicorn main:app --reload --port 8000
```


### Step 6: Test the API

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

Expected response:
```json
{
  "summary": "Requests is a popular Python library for making HTTP requests...",
  "technologies": ["Python", "urllib3", "certifi"],
  "structure": "The project follows a standard Python package layout..."
}
```

## Model Selection

**Model Used**: `moonshotai/Kimi-K2.5` (via Nebius Token Factory) 



## Content Handling Strategy

### What We Include

1. **README Files** (highest priority)
   - Provides the most direct project description
   - Contains setup instructions and use cases

2. **Configuration Files** (medium priority)
   - `package.json` / `setup.py` / `pyproject.toml`: Reveals dependencies and project type
   - `Dockerfile`: Indicates containerization and deployment strategy
   - `Makefile`: Shows common development tasks
   - `requirements.txt` / `go.mod`: Lists main dependencies

3. **Directory Tree Structure** (medium priority)
   - Shows overall project organization
   - Indicates module structure and separation of concerns

4. **Sample Source Files** (low priority)
   - First few source code files give context on implementation patterns
   - Limited to 1500 characters each to respect token limits

### What We Skip

- **Binary Files**: `.o`, `.a`, `.so`, `.dll`, `.exe`, etc.
- **Build Artifacts**: `dist/`, `build/`, `.egg-info/`, `__pycache__/`
- **Dependencies**: `node_modules/`, `.venv/`, `venv/`
- **Lock Files**: `package-lock.json`, `yarn.lock` (already covered by package.json)
- **Minified Files**: `.min.js`, `.min.css`
- **Git Metadata**: `.git/`, `.github/` (workflows are included separately)

### Why This Approach

- **Token Efficiency**: LLM context windows are limited (~2K-4K tokens for request). By selecting only the most relevant files, we maximize the quality of information passed to the model.
- **Relevance**: README + config files + structure give the LLM enough context to understand a project without noise.
- **Speed**: Downloading entire large repositories would be slow and wasteful.
- **Cost**: Fewer tokens = lower API costs.

## API Endpoints

### POST /summarize

Analyze a GitHub repository and generate a summary.

**Request**:
```json
{
  "github_url": "https://github.com/owner/repo"
}
```

**Response** (200 OK):
```json
{
  "summary": "Description of what the project does",
  "technologies": ["Tech1", "Tech2", "Tech3"],
  "structure": "Description of project structure"
}
```

**Error Response** (4xx/5xx):
```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```

### GET /health

Health check endpoint.

**Response** (200 OK):
```json
{
  "status": "ok"
}
```




## Testing Errors

You can trigger different error responses to verify the standardized format:

1. **Missing parameter**:
   ```bash
   curl -i -X POST http://localhost:8000/summarize \
     -H "Content-Type: application/json" \
     -d '{}'
   ```
   Returns `422` with `status: "error"` explaining the validation failure.

2. **Invalid GitHub URL**:
   ```bash
   curl -i -X POST http://localhost:8000/summarize \
     -H "Content-Type: application/json" \
     -d '{"github_url":"not-a-url"}'
   ```
   Returns `400` with a descriptive message.

3. **Missing LLM key** (start server without `NEBIUS_API_KEY`):
   ```bash
   NEBIUS_API_KEY='' uvicorn main:app --reload
   curl -i -X POST http://localhost:8000/summarize \
     -H "Content-Type: application/json" \
     -d '{"github_url":"https://github.com/psf/requests"}'
   ```
   Returns `500` indicating the key is not set.

## Troubleshooting

### "NEBIUS_API_KEY environment variable not set"
Make sure to export the environment variable before starting the server:
```bash
export NEBIUS_API_KEY="your_key"
```

### "Invalid GitHub URL"
Ensure the GitHub URL is in one of these formats:
- `https://github.com/owner/repo`
- `https://github.com/owner/repo.git`
- `git@github.com:owner/repo.git`

### "LLM API error" or "Timeout"
- Check your internet connection
- Verify your NEBIUS_API_KEY is valid
- Try a different repository

### Rate limiting
If you hit GitHub API rate limits, set a GITHUB_TOKEN:
```bash
export GITHUB_TOKEN="your_github_personal_access_token"
```

## Architecture

```
┌─────────────────────────┐
│   Client Request        │
│  POST /summarize        │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   FastAPI Endpoint      │
│   - Parse GitHub URL    │
│   - Validate input      │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   GitHub API Fetcher    │
│   - Fetch README        │
│   - Fetch config files  │
│   - Get tree structure  │
│   - Get source samples  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Content Processor     │
│   - Filter files        │
│   - Build prompt        │
│   - Respect token limit │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Nebius API Call       │
│   - Send prompt         │
│   - Get LLM response    │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Response Parser       │
│   - Extract JSON        │
│   - Structure output    │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Return to Client      │
│   summary, tech, struct │
└─────────────────────────┘
```

## Implementation Details

### GitHub Content Fetching
- Uses GitHub REST API v3 (no authentication required for public repos)
- Fetches directory tree recursively and filters large repositories
- Downloads file contents via base64 encoding for reliability
- Respects file size limits to prevent excessive API calls

### Content Filtering
- Pattern-based filtering ignores common unimportant files
- Prioritizes README and configuration files
- Limits source code samples to first few files
- Caps text sizes (2000 chars for config, 1500 for source)

### LLM Integration
- Uses Nebius Token Factory API for cost-effective summarization
- Constructs a carefully formatted prompt that includes the most relevant information
- Parses JSON response from LLM
- Falls back to manual parsing if JSON extraction fails

## License

MIT

