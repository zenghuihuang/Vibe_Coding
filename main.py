import os
import re
import base64
from typing import Optional
import logging
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import json

# configure simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    # Return standardized error payload
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail}
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request, exc: Exception):
    logger.exception("Unhandled exception occurred")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)}
    )


class SummarizeRequest(BaseModel):
    github_url: str

class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str

class ErrorResponse(BaseModel):
    status: str
    message: str

# GitHub API configuration
GITHUB_API_BASE = "https://api.github.com"

# Nebius Token Factory configuration
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY")
NEBIUS_API_URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"
#NEBIUS_MODEL = "MiniMaxAI/MiniMax-M2.1"
#NEBIUS_MODEL ="zai-org/GLM-4.7-FP8"
NEBIUS_MODEL = "moonshotai/Kimi-K2.5"
NEBIUS_TIMEOUT = 120  # 2 minutes

# File patterns to ignore
IGNORE_PATTERNS = {
    r"\.git",
    r"node_modules",
    r"__pycache__",
    r"\.venv",
    r"venv",
    r"dist",
    r"build",
    r"\.egg-info",
    r"\.pyc",
    r"\.o",
    r"\.a",
    r"\.so",
    r"\.dll",
    r"\.exe",
    r"\.zip",
    r"\.tar",
    r"\.gz",
    r"\.lock",
    r"package-lock\.json",
    r"yarn\.lock",
    r"\.min\.js",
    r"\.min\.css",
}

# Important file patterns (prioritized)
IMPORTANT_FILES = {
    "README.md": 1,
    "README.rst": 1,
    "setup.py": 2,
    "pyproject.toml": 2,
    "package.json": 2,
    "Dockerfile": 3,
    ".github/workflows": 4,
    "Makefile": 3,
    "requirements.txt": 2,
    "go.mod": 2,
}

def should_skip_file(file_path: str) -> bool:
    """Check if a file should be skipped based on ignore patterns."""
    for pattern in IGNORE_PATTERNS:
        if re.search(pattern, file_path, re.IGNORECASE):
            return True
    return False

def get_repo_owner_name(github_url: str) -> tuple[str, str]:
    """Extract owner and repo name from GitHub URL."""
    # Handle various GitHub URL formats
    url = github_url.rstrip("/")
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise ValueError(f"Invalid GitHub URL: {github_url}")
    return match.group(1), match.group(2)

def fetch_github_contents(owner: str, repo: str, headers: dict) -> dict:
    """Fetch repository structure and important files from GitHub."""
    contents = {
        "readme": None,
        "config_files": {},
        "source_samples": {},
        "tree_structure": None,
    }
    
    try:
        # Fetch README
        readme_files = ["README.md", "README.rst", "README.txt"]
        for readme in readme_files:
            try:
                url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{readme}"
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if "content" in data:
                        contents["readme"] = base64.b64decode(data["content"]).decode()
                    break
            except Exception as e:
                logger.debug("Failed to fetch %s: %s", readme, e)
                continue
        
        # Fetch directory structure (limited depth)
        try:
            url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/main?recursive=1"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                # Try master branch
                url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/master?recursive=1"
                resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                tree_data = resp.json().get("tree", [])
                # Build tree structure, skip large files
                tree_lines = []
                for item in tree_data[:100]:  # Limit to first 100 items
                    path = item["path"]
                    if not should_skip_file(path):
                        tree_lines.append(f"{'  ' * path.count('/')}{path}")
                contents["tree_structure"] = "\n".join(tree_lines[:50])  # Max 50 lines
                logger.debug("Tree structure fetched: %d lines", len(tree_lines))
        except Exception as e:
            logger.debug("Failed to fetch tree structure: %s", e)
        
        # Fetch important config files
        important_files_list = [
            "package.json", "setup.py", "pyproject.toml", "go.mod",
            "Dockerfile", "Makefile", "requirements.txt", ".gitignore"
        ]
        
        for filename in important_files_list:
            try:
                url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{filename}"
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if "content" in data and data.get("size", 0) < 5000:
                        contents["config_files"][filename] = base64.b64decode(
                            data["content"]
                        ).decode()[:2000]  # Max 2000 chars
                        logger.debug("Fetched config file: %s", filename)
            except Exception as e:
                logger.debug("Failed to fetch config file %s: %s", filename, e)
                continue
        
        # Fetch some source files for context (first few)
        try:
            url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/main?recursive=1"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/master?recursive=1"
                resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                tree_data = resp.json().get("tree", [])
                source_files = [
                    item["path"] for item in tree_data
                    if not should_skip_file(item["path"]) and
                    any(item["path"].endswith(ext) for ext in [".py", ".js", ".go", ".java", ".rs"])
                ][:3]
                logger.debug("Found %d source files", len(source_files))
                
                for filepath in source_files:
                    try:
                        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{filepath}"
                        resp = requests.get(url, headers=headers, timeout=10)
                        if resp.status_code == 200:
                            data = resp.json()
                            if "content" in data and data.get("size", 0) < 3000:
                                contents["source_samples"][filepath] = base64.b64decode(
                                    data["content"]
                                ).decode()[:1500]
                                logger.debug("Fetched source file: %s", filepath)
                    except Exception as e:
                        logger.debug("Failed to fetch source file %s: %s", filepath, e)
                        continue
        except Exception as e:
            logger.debug("Failed to fetch source files: %s", e)
        
    except Exception as e:
        raise Exception(f"Failed to fetch repository contents: {str(e)}")
    
    return contents

def build_llm_prompt(owner: str, repo: str, contents: dict) -> str:
    """Build a comprehensive prompt for the LLM."""
    prompt = f"""Analyze this GitHub repository and provide a summary in the following JSON format:
{{
  "summary": "A 2-3 sentence description of what this project does",
  "technologies": ["list", "of", "main", "technologies"],
  "structure": "Brief description of project structure"
}}

Repository: {owner}/{repo}

"""
    
    if contents.get("readme"):
        prompt += f"README.md:\n{contents['readme'][:2000]}\n\n"
    
    if contents.get("config_files"):
        prompt += "Configuration files:\n"
        for filename, content in contents["config_files"].items():
            prompt += f"\n{filename}:\n{content}\n"
        prompt += "\n"
    
    if contents.get("tree_structure"):
        prompt += f"Directory structure:\n{contents['tree_structure']}\n\n"
    
    if contents.get("source_samples"):
        prompt += "Sample source code:\n"
        for filepath, content in contents["source_samples"].items():
            prompt += f"\n{filepath}:\n{content}\n"
    
    prompt += "\nProvide your analysis in valid JSON format only."
    return prompt

def call_nebius_api(prompt: str) -> str:
    """Call Nebius API to generate summary."""
    if not NEBIUS_API_KEY:
        logger.error("nebius key not set")
        raise HTTPException(
            status_code=500,
            detail="NEBIUS_API_KEY environment variable not set"
        )
    
    headers = {
        "Authorization": f"Bearer {NEBIUS_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": NEBIUS_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }
    logger.info("sending request to Nebius URL=%s model=%s timeout=%d", NEBIUS_API_URL, NEBIUS_MODEL, NEBIUS_TIMEOUT)
    try:
        response = requests.post(
            NEBIUS_API_URL,
            headers=headers,
            json=payload,
            timeout=NEBIUS_TIMEOUT
        )
        logger.info("Nebius status code: %s", response.status_code)
        response.raise_for_status()
        result = response.json()
        logger.debug("Nebius raw response: %s", result)
        return result["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        logger.error("Nebius request exception: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"LLM API error: {str(e)}"
        )

def parse_llm_response(response: str) -> dict:
    """Parse LLM response and extract structured data."""
    try:
        # Try to extract JSON from response
        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            data = json.loads(json_str)
            return {
                "summary": data.get("summary", "No summary available"),
                "technologies": data.get("technologies", []),
                "structure": data.get("structure", "No structure information available")
            }
    except json.JSONDecodeError:
        pass
    
    # Fallback: extract information manually
    return {
        "summary": response[:500],
        "technologies": ["Unable to parse"],
        "structure": "See summary for details"
    }

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize_repo(request: SummarizeRequest):
    """Summarize a GitHub repository using LLM."""
    logger.info("summarize_repo called with url: %s", request.github_url)
    try:
        # Validate and parse GitHub URL
        owner, repo = get_repo_owner_name(request.github_url)
        
        # Prepare GitHub API headers
        headers = {}
        github_token = os.getenv("GITHUB_TOKEN")
        if github_token:
            headers["Authorization"] = f"token {github_token}"
        headers["Accept"] = "application/vnd.github.v3+json"
        
        # Fetch repository contents
        contents = fetch_github_contents(owner, repo, headers)
        logger.info("fetched contents: readme=%s, config_files=%d entries, samples=%d", 
                    bool(contents.get("readme")), 
                    len(contents.get("config_files", {})),
                    len(contents.get("source_samples", {})))
        
        # Build prompt for LLM
        prompt = build_llm_prompt(owner, repo, contents)
        logger.info("prompt built; length=%d characters", len(prompt))
        
        # Call LLM API
        llm_response = call_nebius_api(prompt)
        logger.info("LLM response received; length=%d", len(llm_response))
        
        # Parse response
        parsed = parse_llm_response(llm_response)
        
        return SummarizeResponse(
            summary=parsed["summary"],
            technologies=parsed["technologies"],
            structure=parsed["structure"]
        )
        
    except ValueError as e:
        logger.error("ValueError in summarize_repo: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled exception in summarize_repo")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/debug/fetch")
async def debug_fetch(request: SummarizeRequest):
    """Debug endpoint: fetch repository contents from GitHub and return them directly.

    This bypasses the LLM call and is intended for local testing only.
    """
    try:
        owner, repo = get_repo_owner_name(request.github_url)
        headers = {}
        github_token = os.getenv("GITHUB_TOKEN")
        if github_token:
            headers["Authorization"] = f"token {github_token}"
        headers["Accept"] = "application/vnd.github.v3+json"

        contents = fetch_github_contents(owner, repo, headers)
        return contents
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
