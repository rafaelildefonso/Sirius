import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    print(f"Python path: {sys.path}")
    print(f"Executable: {sys.executable}")
    
    from groq import Groq
    print("SUCCESS: groq package imported successfully!")
    
    # Check for API key
    key = os.getenv("GROQ_API_KEY")
    if not key:
        # Try loading from .env
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if line.startswith("GROQ_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    
    if key:
        print(f"Found API Key: {key[:10]}...")
        client = Groq(api_key=key)
        # Try a tiny completion
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            model="llama3-8b-8192",
            max_tokens=5
        )
        print(f"API SUCCESS: {chat_completion.choices[0].message.content}")
    else:
        print("ERROR: No GROQ_API_KEY found")

except ImportError as e:
    print(f"IMPORT ERROR: {e}")
except Exception as e:
    print(f"OTHER ERROR: {e}")
