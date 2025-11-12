# AutoCritique — Full Implementation Guide (Non‑Dockerized)

This document describes the complete implementation and local development workflow for the AutoCritique project (Streamlit UI + ReflectionAgent). It is targeted for local development and deployment on a developer machine (no Docker, no containerization). It explains the architecture, file layout, setup, running instructions, verification behavior, security considerations, testing, and common maintenance tasks.

Audience: developers who will run and maintain the project locally, run tests, add providers (Groq), or extend the verifier. This guide assumes you have basic familiarity with Python, virtual environments, and command-line usage.

Table of contents
- Project overview
- Architecture & data flow (short)
- File map
- Prerequisites
- Local setup (step-by-step)
- Environment variables and .env
- Running the app (Streamlit)
- How the reflection loop works (detailed)
- Verification / code execution behavior
- Using a real LLM provider (Groq)

--------------------------------------------------------------------------------
Project overview
--------------------------------------------------------------------------------

AutoCritique demonstrates the "Reflection Pattern": a generator LLM produces a candidate (code or text), a reflector LLM critiques it, and the generator uses that critique to produce a revised candidate. The Streamlit UI collects a single user task and returns ONLY the final assistant output. The ReflectionAgent executes the full loop on the backend and can verify (heuristic) generated Python code.

Key goals:
- Simple, local-first developer experience (no Docker).
- Safe offline development via a MockClient fallback.
- Hardcoded (backend) configuration so the UI is simple for end users.
- A verification helper that performs syntax and small heuristic tests (developer-only; uses exec()).

--------------------------------------------------------------------------------
Architecture & data flow (concise)
--------------------------------------------------------------------------------

- User (browser) interacts with Streamlit UI (`app.py`) and submits a task.
- Streamlit instantiates `ReflectionAgent` (backend, `agentic_patterns/reflection_agent.py`) with a client:
  - Prefer Groq if API keys present, otherwise fall back to `MockClient`.
- `ReflectionAgent.run`:
  - Maintains `generation_history` (list of messages).
  - For each iteration up to N_STEPS:
    - Call generation LLM → receive generation_text (assistant content).
    - Call reflection LLM with reflection prompt + generation_text → receive critique_text.
    - Append critique to `generation_history` as user message.
    - Stop early if critique includes `<OK>` or a line equal to `OK`.
  - Returns `{ final_assistant, rounds, generation_history }`.
- Streamlit UI displays only `final_assistant` (user-facing).
- Developer utilities in `ReflectionAgent` can:
  - Extract python code blocks from generated content.
  - Run `ast.parse` and heuristic tests using `exec()` to verify correctness (developer-only).

--------------------------------------------------------------------------------
File map
--------------------------------------------------------------------------------

- app.py
  - Streamlit UI. Hardcoded backend config; collects only the user task and displays the final output.
- agentic_patterns/
  - reflection_agent.py
    - ReflectionAgent class, MockClient fallback, code extraction & verification helpers.
- requirements.txt
  - Project dependencies (streamlit, python-dotenv, groq, as optional).
- README.md, docs/*
  - Documentation and usage instructions (optional).
- .env (optional local file)
  - environment variables (GROQ_API_KEY,_API_KEY, DEFAULT_MODEL, DEV_VIEW flag if added).

--------------------------------------------------------------------------------
Prerequisites (local machine)
--------------------------------------------------------------------------------

- Python 3.10+ (3.11 recommended)
- pip
- Git (optional for versioning)
- Internet access if using a real LLM provider (Groq or)
- Recommended: create a Python virtual environment for project isolation

--------------------------------------------------------------------------------
Local setup (step-by-step)
--------------------------------------------------------------------------------

1. Clone the repository (if applicable)
   - git clone <repo-url>
   - cd <repo-dir>

2. Create and activate a virtual environment
   - macOS / Linux:
     - python -m venv .venv
     - source .venv/bin/activate
   - Windows (PowerShell):
     - python -m venv .venv
     - .\.venv\Scripts\Activate.ps1

3. Install dependencies
   - pip install -r requirements.txt
   - If you only need the UI locally and want to avoid optional SDKs:
     - pip install streamlit python-dotenv

4. Create a .env file (optional)
   - See the "Environment variables and .env" section below for recommended contents.

--------------------------------------------------------------------------------
Environment variables and .env
--------------------------------------------------------------------------------

Create `.env` at the project root (optional). Example:

```
GROQ_API_KEY=_API_KEY=
DEFAULT_MODEL=llama-3.3-70b-versatile
```

- If you want to use Groq or instead of MockClient, fill the appropriate API key.
- Leave both blank to run the app locally with the MockClient.

Note: Never commit secrets / API keys. Add `.env` to `.gitignore`.

--------------------------------------------------------------------------------
Running the app (Streamlit)
--------------------------------------------------------------------------------

1. Ensure your virtualenv is active and dependencies installed.
2. Run the UI:

```
streamlit run app.py
```

3. In the browser:
   - Enter the user task (e.g., "Generate a Python implementation of Merge Sort").
   - Click the "Run (hardcoded backend settings)" button.
   - Wait for the spinner; when complete you will see ONLY the Final Assistant Output.

Remarks:
- If no API keys are present, the ReflectionAgent uses `MockClient` to produce deterministic test responses.
- Backend settings (MODEL, prompts, N_STEPS, STOP_ON_OK, delay) are hardcoded in `app.py`.

--------------------------------------------------------------------------------
How the reflection loop works (detailed)
--------------------------------------------------------------------------------

1. The UI calls `ReflectionAgent.run(user_msg, generation_system_prompt, reflection_system_prompt, n_steps, ...)`.
2. `generation_history` is initialized:
   - [{"role":"system","content": generation_system_prompt}, {"role":"user","content": user_msg}]
3. For step = 1..n_steps:
   - Call generation:
     - client.chat.completions.create(messages=generation_history, model=model)
     - Extract assistant content → `generation_text`
     - Append {"role":"assistant", "content": generation_text} to `generation_history`
   - Call reflection:
     - reflection_history = [{"role":"system","content": reflection_system_prompt}, {"role":"user","content": generation_text}]
     - client.chat.completions.create(messages=reflection_history, model=model)
     - Extract `critique_text`
     - Append {"role":"user","content": critique_text} to `generation_history`
   - Save round: {step, generation_text, critique_text}
   - Check early-stop: if critique contains `<OK>` (case-insensitive) or any line that equals "OK" → break
4. Return: { final_assistant: last generation_text, rounds: list, generation_history: list }

Data shapes:
- messages: list[{"role": "system" | "user" | "assistant", "content": str}]
- returned LLM response: expected at resp["choices"][0]["message"]["content"] or resp.choices[0].message.content

--------------------------------------------------------------------------------
Verification / code execution behavior (developer-only)
--------------------------------------------------------------------------------

ReflectionAgent contains helpers:
- extract_code_blocks(text) → extracts ```python code blocks
- verify_code(code) → does:
  - ast.parse(code) to validate syntax
  - finds first function defined (FunctionDef) and chooses it for tests if available
  - heuristic tests (if function name contains "sort", run sorting test vectors)
  - exec the code in a restricted namespace to run test calls

Important security note (read carefully):
- verify_code uses exec() to execute generated code in the running process. This is DANGEROUS for untrusted code. Only run verification locally in controlled environments.
- For production or any environment exposed to untrusted users, move verification into an isolated sandbox (Docker container, restricted subprocess with seccomp, separate evaluation service, Firecracker microVM, etc.).

Developer suggestion:
- Add an environment flag (e.g., `DEV_VIEW=true` or `SKIP_EXEC_VERIFY=true`) to disable exec-based verification if needed.
- Prefer to run verification in a subprocess with a resource/time limit and confined permissions.

--------------------------------------------------------------------------------
Using a real LLM provider (Groq /)
--------------------------------------------------------------------------------

Behavior:
- If GROQ_API_KEY present in the environment, app.py will attempt to instantiate `Groq(api_key=...)`.
- Else if_API_KEY present, app.py will instantiate a small wrapper that calls .ChatCompletion.create(...)`.
- Else, MockClient is used.

Steps to enable:
1. Sign up for an account, obtain an API key.
2. Set environment variable:
   - export_API_KEY="sk-..."
3. Install SDK:
   - pip install
4. Run the UI; the app will use the wrapper to call the model ID specified in MODEL (adjust MODEL to an available model: e.g., "gpt-4o", "gpt-4", or a supported chat model).

Steps to enable Groq:
1. Obtain GROQ_API_KEY.
2. Set environment variable:
   - export GROQ_API_KEY="..."
3. Install Groq SDK (if required) and run.

Notes:
- The code expects the model to accept the `messages` format. If your provider requires a different call shape, add a small adapter that returns a response where the assistant content is available as resp["choices"][0]["message"]["content"] (or update `_call_model` extraction logic).
- Be mindful of rate limits, costs and model availability when running multiple iterations.

--------------------------------------------------------------------------------
Development view / debugging (optional)
--------------------------------------------------------------------------------

By default the UI hides intermediate rounds and verification. For local debugging you may want to:
- Temporarily modify `app.py` to display `result["rounds"]` and `verification` in the UI.
- Or add an environment flag `DEV_VIEW=true` and guard the debug display with `if os.getenv("DEV_VIEW")=="true": ...`.

Example (small snippet to add in app.py after result is returned):

```python
if os.getenv("DEV_VIEW", "false").lower() in ("1", "true", "yes"):
    st.markdown("### Developer Trace (rounds)")
    for r in result["rounds"]:
        st.markdown(f"Step {r['step']}")
        st.code(r["generation_text"])
        st.code(r["critique_text"])
```

Remember to remove or guard this behind authentication before sharing the UI widely.

--------------------------------------------------------------------------------
How to extend or integrate LangGraph later
--------------------------------------------------------------------------------

If you want to replace the in-house loop with an orchestrator like LangGraph:

1. Create three nodes:
   - generator-node (calls LLM for generation)
   - reflector-node (calls LLM for critique)
   - verifier-node (executes verification in a sandboxed service)
2. Build a LangGraph flow that:
   - feeds user prompt to generator-node,
   - passes generation to reflector-node,
   - appends critique and loops until N iterations or a stop condition,
   - sends final generation to verifier-node.
3. Replace `ReflectionAgent.run` call in `app.py` with a call that triggers the LangGraph flow and waits for final result.

Notes:
- LangGraph adds observability and better orchestration; helpful if you later need multiple reviewers, parallel reviewers, or complex branching.


