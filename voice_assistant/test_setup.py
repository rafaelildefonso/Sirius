"""Test voice assistant setup."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_audio():
    """Test audio system."""
    print("\n🎤 Testando sistema de áudio...")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devices = [d for d in devices if d['max_input_channels'] > 0]
        output_devices = [d for d in devices if d['max_output_channels'] > 0]

        if not input_devices:
            print("  ❌ Nenhum dispositivo de entrada (microfone) encontrado!")
            return False

        if not output_devices:
            print("  ❌ Nenhum dispositivo de saída (alto-falante) encontrado!")
            return False

        print(f"  ✅ {len(input_devices)} microfone(s) encontrado(s)")
        print(f"  ✅ {len(output_devices)} alto-falante(s) encontrado(s)")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False


def test_stt():
    """Test speech-to-text with fallback options."""
    print("\n🗣️ Testando reconhecimento de voz...")

    # Try faster-whisper first
    try:
        from voice_assistant.stt import SpeechToText
        stt = SpeechToText(model_size="tiny")
        print("  ⏳ Tentando faster-whisper...")
        stt._ensure_model()
        print("  ✅ faster-whisper carregado!")
        return True
    except Exception as e:
        print(f"  ⚠️  faster-whisper falhou: {e}")

    # Try openai-whisper
    try:
        from voice_assistant.stt_alt import WhisperSTT
        stt = WhisperSTT(model_size="tiny")
        print("  ⏳ Tentando openai-whisper...")
        stt._ensure_model()
        print("  ✅ openai-whisper carregado!")
        return True
    except Exception as e:
        print(f"  ⚠️  openai-whisper falhou: {e}")

    # Try speech_recognition
    try:
        from voice_assistant.stt_alt import SpeechRecognitionSTT
        stt = SpeechRecognitionSTT()
        print("  ✅ speech_recognition disponível (usa Google API - requer internet)")
        return True
    except Exception as e:
        print(f"  ❌ Todos os STT falharam. Último erro: {e}")
        return False


def test_tts():
    """Test text-to-speech with fallback options."""
    print("\n🔊 Testando síntese de voz...")

    # Try Kokoro first
    try:
        from voice_assistant.tts import TextToSpeech
        tts = TextToSpeech()
        print("  ⏳ Tentando Kokoro...")
        tts._ensure_pipeline()
        print("  ✅ Kokoro TTS carregado!")
        return True
    except Exception as e:
        print(f"  ⚠️  Kokoro falhou: {e}")

    # Try pyttsx3
    try:
        from voice_assistant.tts_alt import Pyttsx3TTS
        tts = Pyttsx3TTS()
        print("  ⏳ Tentando pyttsx3...")
        tts._ensure_engine()
        print("  ✅ pyttsx3 TTS carregado (voz do Windows)!")
        return True
    except Exception as e:
        print(f"  ⚠️  pyttsx3 falhou: {e}")

    # Try Windows SAPI
    try:
        from voice_assistant.tts_alt import WindowsNativeTTS
        tts = WindowsNativeTTS()
        print("  ✅ Windows SAPI TTS disponível!")
        return True
    except Exception as e:
        print(f"  ❌ Todos os TTS falharam. Último erro: {e}")
        return False


def test_llm():
    """Test Ollama connection."""
    print("\n🧠 Testando conexão com Ollama...")
    try:
        from voice_assistant.llm import OllamaClient
        client = OllamaClient()

        if client.health():
            models = client.list_models()
            print(f"  ✅ Ollama conectado! Modelos: {', '.join(models[:3])}")
            return True
        else:
            print("  ❌ Ollama não está rodando!")
            print("     Execute: ollama serve")
            return False
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False


def test_hotkey():
    """Test hotkey system."""
    print("\n⌨️ Testando sistema de atalhos...")
    try:
        from voice_assistant.hotkey import PushToTalkHandler
        # Just test instantiation, don't start
        handler = PushToTalkHandler(
            on_push=lambda: None,
            on_release=lambda: None,
        )
        print("  ✅ Sistema de atalhos OK!")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("🧪 Testando setup do Assistente de Voz")
    print("=" * 60)

    results = {
        "Áudio": test_audio(),
        "STT (faster-whisper)": test_stt(),
        "TTS (kokoro)": test_tts(),
        "LLM (Ollama)": test_llm(),
        "Atalhos": test_hotkey(),
    }

    print("\n" + "=" * 60)
    print("📊 Resultados:")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "✅ OK" if passed else "❌ FALHA"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 Tudo pronto! Execute: uv run python voice-assistant.py")
    else:
        print("⚠️  Alguns componentes falharam. Corrija antes de continuar.")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
