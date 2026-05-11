"""User profile configuration loaded from frontend onboarding settings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AssistantPermissions:
    """Permissions configured during onboarding."""
    
    fileAccess: bool = True
    commandExecution: bool = False
    internetAccess: bool = True
    externalIntegrations: bool = True
    autonomousMode: bool = False


@dataclass
class UserProfile:
    """Complete user profile from onboarding wizard."""
    
    userName: str = ""
    assistantStyle: str = "friendly"  # professional, friendly, technical, creative
    permissions: AssistantPermissions = field(default_factory=AssistantPermissions)
    language: str = "pt"  # pt, en, es
    theme: str = "system"  # light, dark, system
    notifications: bool = True
    fontSize: str = "default"  # small, default, large
    onboardingCompleted: bool = False


class ProfileManager:
    """Manages loading and accessing user profile."""
    
    # Possible locations for the profile file
    POSSIBLE_PATHS = [
        # Same directory as the user_profile module (voice_assistant/profile.json)
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json"),
        # Tauri dev build location
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                     "frontend", "src-tauri", "voice_assistant", "profile.json"),
        # Frontend localStorage export location
        os.path.expanduser("~/.sirius/profile.json"),
        os.path.expanduser("~/.sirius/assistant-profile.json"),
        # Project directory
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                     "frontend", "profile.json"),
        # Current working directory
        "profile.json",
        "assistant-profile.json",
    ]
    
    def __init__(self):
        self.profile: UserProfile = UserProfile()
        self._load_profile()
    
    def _load_profile(self) -> None:
        """Try to load profile from various locations."""
        for path in self.POSSIBLE_PATHS:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self.profile = self._parse_profile(data)
                    print(f"[Profile] Loaded user profile from {path}")
                    print(f"[Profile] User: {self.profile.userName}, Style: {self.profile.assistantStyle}")
                    return
                except Exception as e:
                    print(f"[Profile] Failed to load from {path}: {e}")
                    continue
        
        print("[Profile] No profile found, using defaults")
    
    def load_from_json(self, json_str: str) -> bool:
        """Load profile from JSON string (e.g., from API)."""
        try:
            data = json.loads(json_str)
            self.profile = self._parse_profile(data)
            print(f"[Profile] Loaded from JSON: {self.profile.userName}")
            return True
        except Exception as e:
            print(f"[Profile] Failed to load from JSON: {e}")
            return False
    
    def save_to_default_path(self) -> bool:
        """Save current profile to the default path."""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            default_path = os.path.join(script_dir, "profile.json")
            data = {
                "userName": self.profile.userName,
                "assistantName": getattr(self.profile, 'assistantName', 'Sirius'),
                "assistantStyle": self.profile.assistantStyle,
                "permissions": {
                    "fileAccess": self.profile.permissions.fileAccess,
                    "commandExecution": self.profile.permissions.commandExecution,
                    "internetAccess": self.profile.permissions.internetAccess,
                    "externalIntegrations": self.profile.permissions.externalIntegrations,
                    "autonomousMode": self.profile.permissions.autonomousMode,
                },
                "language": self.profile.language,
                "theme": self.profile.theme,
                "notifications": self.profile.notifications,
                "fontSize": self.profile.fontSize,
                "onboardingCompleted": self.profile.onboardingCompleted,
            }
            with open(default_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[Profile] Saved to {default_path}")
            return True
        except Exception as e:
            print(f"[Profile] Failed to save: {e}")
            return False
    
    def _parse_profile(self, data: dict) -> UserProfile:
        """Parse profile from JSON data."""
        perms_data = data.get('permissions', {})
        permissions = AssistantPermissions(
            fileAccess=perms_data.get('fileAccess', True),
            commandExecution=perms_data.get('commandExecution', False),
            internetAccess=perms_data.get('internetAccess', True),
            externalIntegrations=perms_data.get('externalIntegrations', True),
            autonomousMode=perms_data.get('autonomousMode', False),
        )
        
        return UserProfile(
            userName=data.get('userName', ''),
            assistantStyle=data.get('assistantStyle', 'friendly'),
            permissions=permissions,
            language=data.get('language', 'pt'),
            theme=data.get('theme', 'system'),
            notifications=data.get('notifications', True),
            fontSize=data.get('fontSize', 'default'),
            onboardingCompleted=data.get('onboardingCompleted', False),
        )
    
    def get_style_prompt(self) -> str:
        """Get the personality/style prompt based on selected style."""
        style_prompts = {
            'professional': (
                "Você é Sirius, um assistente profissional e eficiente. "
                "Comunique-se de forma formal, direta e focada em produtividade. "
                "Seja cordial mas mantenha um tom corporativo. "
                "Priorize clareza e objetividade nas respostas."
            ),
            'friendly': (
                "Você é Sirius, um assistente pessoal com personalidade amigável e conversacional. "
                "Comunique-se de forma casual e acolhedora, como conversando com um amigo. "
                "Use expressões coloquiais brasileiras naturais (prontinho, beleza, show, etc). "
                "Seja gentil e próximo ao usuário."
            ),
            'technical': (
                "Você é Sirius, um assistente técnico e analítico. "
                "Comunique-se de forma precisa, detalhada e focada em dados. "
                "Forneça informações técnicas completas e bem estruturadas. "
                "Seja metódico e rigoroso nas explicações."
            ),
            'creative': (
                "Você é Sirius, um assistente criativo e inspirador. "
                "Comunique-se de forma entusiasmada e pensativa. "
                "Ofereça perspectivas diferentes e sugestões inovadoras. "
                "Seja imaginativo e incentive o brainstorm."
            ),
        }
        
        return style_prompts.get(self.profile.assistantStyle, style_prompts['friendly'])
    
    def get_user_greeting(self) -> str:
        """Get personalized greeting with user name."""
        if self.profile.userName:
            return f"Olá {self.profile.userName}!"
        return "Olá!"
    
    def get_full_system_prompt(self, base_prompt: str) -> str:
        """Combine base prompt with user profile settings."""
        style_prompt = self.get_style_prompt()
        
        # Add user name context if available
        user_context = ""
        if self.profile.userName:
            user_context = f"\nO nome do usuário é {self.profile.userName}. Use o nome ocasionalmente nas respostas para personalizar."
        
        # Add permission restrictions
        restrictions = []
        if not self.profile.permissions.commandExecution:
            restrictions.append("NÃO execute comandos de terminal ou scripts sem confirmação explícita.")
        if not self.profile.permissions.internetAccess:
            restrictions.append("NÃO faça buscas na internet.")
        if not self.profile.permissions.fileAccess:
            restrictions.append("NÃO acesse arquivos locais do usuário.")
        if not self.profile.permissions.autonomousMode:
            restrictions.append("SEMPRE peça confirmação antes de executar ações importantes.")
        
        restrictions_text = ""
        if restrictions:
            restrictions_text = "\n\nRESTRIÇÕES DE PERMISSÃO:\n" + "\n".join(f"- {r}" for r in restrictions)
        
        return f"{style_prompt}{user_context}\n\n{base_prompt}{restrictions_text}"
    
    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed based on permissions."""
        tool_permission_map = {
            'search_web': 'internetAccess',
            'browser_search': 'internetAccess',
            'browser_search_and_click': 'internetAccess',
            'open_url': 'internetAccess',
            'execute_command': 'commandExecution',
            'run_script': 'commandExecution',
            'read_file': 'fileAccess',
            'write_file': 'fileAccess',
            'open_application': 'externalIntegrations',
            'youtube_search_and_play': 'externalIntegrations',
        }
        
        permission_key = tool_permission_map.get(tool_name)
        if permission_key:
            return getattr(self.profile.permissions, permission_key, True)
        
        # Tools not in the map are allowed by default
        return True


# Global profile manager instance
_profile_manager: Optional[ProfileManager] = None


def get_profile_manager() -> ProfileManager:
    """Get or create the global profile manager instance."""
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = ProfileManager()
    return _profile_manager
