import 'dart:convert';
import '../../../core/ai/gemma_engine.dart';

class NoteClassification {
  final String summary;
  final List<String> tags;
  final String? suggestedFolder;

  NoteClassification({
    required this.summary,
    required this.tags,
    this.suggestedFolder,
  });

  factory NoteClassification.fromJson(Map<String, dynamic> json) {
    return NoteClassification(
      summary: json['summary'] as String? ?? '',
      tags: (json['tags'] as List<dynamic>?)?.cast<String>() ?? [],
      suggestedFolder: json['suggested_folder'] as String?,
    );
  }
}

class NoteClassifier {
  static bool _gemmaAvailable = false;
  static String? _lastError;

  static String? get lastError => _lastError;

  /// Check if Gemma is ready for local classification.
  static Future<bool> isAvailable() async {
    try {
      _gemmaAvailable = await GemmaEngine.checkModelExists();
      if (!_gemmaAvailable) {
        _lastError = 'Modelo Gemma indisponível neste aparelho';
      }
      return _gemmaAvailable;
    } catch (e) {
      _lastError = 'Não foi possível verificar o Gemma: $e';
      return false;
    }
  }

  /// Classify a note using Gemma. Returns null if Gemma is unavailable.
  static Future<NoteClassification?> classify({
    required String content,
    required String category,
    String? title,
  }) async {
    _lastError = null;
    if (!_gemmaAvailable) {
      final available = await isAvailable();
      if (!available) return null;
    }

    try {
      // A model file on disk does not mean the native inference session is
      // ready.  Classification runs after saving, so initialize lazily here
      // and let the native side return immediately when it is already ready.
      final initialized = await GemmaEngine.initialize();
      if (!initialized) {
        _lastError = 'Gemma não conseguiu inicializar o modelo';
        return null;
      }
      final prompt = _buildPrompt(
        content: content,
        category: category,
        title: title,
      );
      final response = await GemmaEngine.generate(prompt);
      final parsed = _parseResponse(response);
      if (parsed == null) {
        _lastError = 'Gemma retornou uma classificação inválida';
      }
      return parsed;
    } catch (e) {
      _lastError = 'Erro na classificação local: $e';
      print('[NoteClassifier] Gemma classification failed: $e');
      return null;
    }
  }

  static String _buildPrompt({
    required String content,
    required String category,
    String? title,
  }) {
    final titlePart = title != null && title.isNotEmpty
        ? 'Título: $title\n'
        : '';
    return '''Analise a seguinte anotação e retorne APENAS um JSON válido (sem markdown, sem texto adicional):

${titlePart}Categoria selecionada: $category
Conteúdo:
$content

Retorne um JSON com exatamente estes campos:
{
  "summary": "resumo curto em uma linha",
  "tags": ["tag1", "tag2", "tag3"],
  "suggested_folder": "nome_da_pasta_sugerida"
}

Regras:
- summary: máximo 100 caracteres, em português
- tags: 2 a 5 palavras-chave relevantes, em minúsculo
- suggested_folder: pasta no Obsidian que melhor organiza este conteúdo (ex: "Cursos", "Ideias", "Referências", "Reuniões")
''';
  }

  static NoteClassification? _parseResponse(String response) {
    try {
      // Try to extract JSON from the response (Gemma may wrap it in text).
      final jsonStart = response.indexOf('{');
      final jsonEnd = response.lastIndexOf('}');
      if (jsonStart == -1 || jsonEnd == -1 || jsonEnd <= jsonStart) return null;

      final jsonStr = response.substring(jsonStart, jsonEnd + 1);
      final json = jsonDecode(jsonStr) as Map<String, dynamic>;
      return NoteClassification.fromJson(json);
    } catch (e) {
      print('[NoteClassifier] Failed to parse Gemma response: $e');
      return null;
    }
  }
}
