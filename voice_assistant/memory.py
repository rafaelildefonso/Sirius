import json
import os
from typing import Any, Dict, List

class MemoryManager:
    """Manages persistent memory for the voice assistant."""
    
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self.memory: Dict[str, Any] = {}
        self.load()
        
    def load(self):
        """Load memory from disk."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    self.memory = json.load(f)
            except Exception as e:
                print(f"[Memory] Error loading memory: {e}")
                self.memory = {}
        else:
            self.memory = {}
            
    def save(self):
        """Save memory to disk."""
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self.memory, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Memory] Error saving memory: {e}")
            
    def set(self, key: str, value: Any):
        """Store a value in memory."""
        self.memory[key] = value
        self.save()
        
    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value from memory."""
        return self.memory.get(key, default)
        
    def delete(self, key: str):
        """Remove a value from memory."""
        if key in self.memory:
            del self.memory[key]
            self.save()
            
    def get_all(self) -> Dict[str, Any]:
        """Return all memory."""
        return self.memory

    def get_summary_string(self) -> str:
        """Return a string summary of memory for the LLM prompt."""
        if not self.memory:
            return "Nenhuma memória persistente disponível."
            
        summary = "Memórias persistentes (preferências do usuário):\n"
        for k, v in self.memory.items():
            summary += f"- {k}: {v}\n"
        return summary

    def save_conversation(self, conversation_history: List[Dict[str, Any]]):
        """Save conversation history to memory.
        
        Extracts and stores key facts from the conversation for future context.
        """
        if not conversation_history:
            return
            
        # Store the last few messages as recent context
        recent = conversation_history[-5:] if len(conversation_history) > 5 else conversation_history
        self.set("recent_conversation", recent)
        
        # Try to extract key facts from assistant responses
        for msg in conversation_history:
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                # Look for factual information (dates, names, preferences)
                if content and len(content) > 10 and not content.startswith("Desculpe"):
                    # Store significant responses as memory facts
                    existing_facts = self.get("conversation_facts", [])
                    if isinstance(existing_facts, list) and content not in existing_facts:
                        existing_facts.append(content[:200])  # Limit length
                        if len(existing_facts) > 10:  # Keep only last 10
                            existing_facts = existing_facts[-10:]
                        self.set("conversation_facts", existing_facts)
