import os
import streamlit as st
from dotenv import load_dotenv
load_dotenv()

# Hardcoded backend settings (no sidebar)
MODEL = "llama-3.3-70b-versatile"
GENERATION_SYSTEM_PROMPT = (
    "You are a Python programmer tasked with generating high quality Python code. "
    "When asked to provide code, respond with a single python code block (```python ... ```)."
)
REFLECTION_SYSTEM_PROMPT = (
    "You are an expert reviewer. Provide critique and actionable recommendations for the user's code. "
    "If the code requires no further changes, reply with exactly '<OK>'."
)
N_STEPS = 5
STOP_ON_OK = True
DELAY_BETWEEN_STEPS = 0.3

# Import the ReflectionAgent (from local file or package path)
try:
    from reflection_agent import ReflectionAgent  # type: ignore
except Exception:
    try:
        from agentic_patterns.reflection_agent import ReflectionAgent  # type: ignore
    except Exception:
        ReflectionAgent = None

st.set_page_config(page_title="Python Code Generation", layout="wide")
st.title("AutoCritique")

st.markdown(
"""
- Only the task and user instruction is requested here.
"""
)

# Input: single user message (task)
user_msg = st.text_area(
    "Task / instruction for the agent (e.g., 'Generate a Python implementation of Merge Sort')",
    value="Generate a Python implementation of the Merge Sort algorithm",
    height=200,
)

client = None
# Try Groq if GROQ_API_KEY found
try:
    if os.getenv("GROQ_API_KEY"):
        from groq import Groq  # type: ignore
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
except Exception:
    client = None

# Try OpenAI if OPENAI_API_KEY present
try:
    if client is None and os.getenv("OPENAI_API_KEY"):
        import openai  # type: ignore
        openai.api_key = os.getenv("OPENAI_API_KEY")

        class OpenAIWrapper:
            class chat:
                class completions:
                    @staticmethod
                    def create(messages, model):
                        return openai.ChatCompletion.create(model=model, messages=messages)

        client = OpenAIWrapper()
except Exception:
    client = None

if ReflectionAgent is None:
    st.error("ReflectionAgent not found. Ensure agentic_patterns/reflection_agent.py or reflection_agent.py exists.")
else:
    if st.button("Run"):
        agent = ReflectionAgent(client=client, model=MODEL, stop_on_ok=STOP_ON_OK)
        with st.spinner("Running generation → reflection loop..."):
            result = agent.run(
                user_msg=user_msg,
                generation_system_prompt=GENERATION_SYSTEM_PROMPT,
                reflection_system_prompt=REFLECTION_SYSTEM_PROMPT,
                n_steps=N_STEPS,
                verbose=False,
                delay_between_steps=DELAY_BETWEEN_STEPS,
            )
        st.success("Done.")

        # Show ONLY the final assistant output to the user
        st.markdown("## Final Assistant Output")
        final_output = result.get("final_assistant", "")
        if final_output.strip() == "":
            st.warning("The assistant returned an empty response.")
        else:
            st.code(final_output, language="text")
