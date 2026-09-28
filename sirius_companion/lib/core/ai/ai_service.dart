import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'gemma_engine.dart';

enum GemmaStatus {
  unchecked,
  available,
  unavailable,
  downloading,
  initializing,
  ready,
  error,
}

class GemmaStatusNotifier extends StateNotifier<GemmaStatus> {
  GemmaStatusNotifier() : super(GemmaStatus.unchecked);

  void set(GemmaStatus status) => state = status;

  String get label {
    switch (state) {
      case GemmaStatus.unchecked:
        return 'Não verificado';
      case GemmaStatus.available:
        return 'Hardware compatível';
      case GemmaStatus.unavailable:
        return 'Hardware incompatível';
      case GemmaStatus.downloading:
        return 'Baixando modelo...';
      case GemmaStatus.initializing:
        return 'Inicializando modelo...';
      case GemmaStatus.ready:
        return 'Pronto';
      case GemmaStatus.error:
        return 'Erro';
    }
  }
}

final gemmaStatusProvider =
    StateNotifierProvider<GemmaStatusNotifier, GemmaStatus>((ref) {
      return GemmaStatusNotifier();
    });

class AiService {
  static bool _initialized = false;
  static String? _lastError;
  static Future<bool>? _initializing;

  Future<bool> checkHardware() async {
    try {
      return await GemmaEngine.checkHardware();
    } on GemmaException {
      return false;
    }
  }

  Future<bool> initialize({void Function(double, String)? onProgress}) async {
    if (_initialized) return true;
    if (_initializing != null) return _initializing!;
    _initializing = _initialize(onProgress);
    try {
      return await _initializing!;
    } finally {
      _initializing = null;
    }
  }

  Future<bool> _initialize(void Function(double, String)? onProgress) async {
    try {
      final result = await GemmaEngine.initialize(
        showProgress: onProgress != null,
        onProgress: onProgress,
      );
      _initialized = result;
      _lastError = null;
      return result;
    } on GemmaException catch (e) {
      _initialized = false;
      _lastError = e.message;
      return false;
    }
  }

  String? get lastError => _lastError;

  Future<String?> processText(String text) async {
    if (!_initialized) {
      final hardwareOk = await checkHardware();
      if (!hardwareOk) {
        _lastError = 'Hardware incompatível para IA local';
        return null;
      }
      final inited = await initialize();
      if (!inited) {
        _lastError = 'Falha ao inicializar modelo local: $_lastError';
        return null;
      }
    }

    try {
      final prompt = _buildPrompt(text);
      final response = await GemmaEngine.generate(prompt);
      if (response.trim().isEmpty) {
        _lastError = 'Resposta vazia do modelo local';
        return null;
      }
      _lastError = null;
      return response;
    } on GemmaException catch (e) {
      _lastError = 'Erro na geração: ${e.message}';
      return null;
    }
  }

  String _buildPrompt(String text) {
    return 'You are an AI assistant running on a mobile device. '
        'The user has sent the following command: "$text". '
        'Respond concisely in Portuguese with a helpful answer or confirmation. '
        'If the command requires complex actions (web search, file access, computer control), '
        'respond with "FALLBACK: This command requires the desktop assistant."';
  }

  bool get isInitialized => _initialized;

  Future<void> shutdown() async {
    await GemmaEngine.shutdown();
    _initialized = false;
    _lastError = null;
    _initializing = null;
  }
}
