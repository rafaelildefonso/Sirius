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
