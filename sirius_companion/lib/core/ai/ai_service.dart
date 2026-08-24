import 'dart:convert';
import 'package:uuid/uuid.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../config/constants.dart';
import '../storage/database/database.dart';
import '../storage/repositories/sync_repository.dart';
import 'gemma_engine.dart';

enum GemmaStatus {
  unchecked,
  available,
  unavailable,
  downloading,
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
  bool _initialized = false;

  Future<bool> checkHardware() async {
    try {
      return await GemmaEngine.checkHardware();
    } on GemmaException {
      return false;
    }
  }

  Future<bool> initialize() async {
    try {
      final result = await GemmaEngine.initialize();
      _initialized = result;
      return result;
    } on GemmaException {
      _initialized = false;
      return false;
    }
  }

  Future<String?> processText(String text) async {
    if (!_initialized) {
      final hardwareOk = await checkHardware();
      if (!hardwareOk) {
        await _fallback(text);
        return null;
      }
      final inited = await initialize();
      if (!inited) {
        await _fallback(text);
        return null;
      }
    }

    try {
      final prompt = _buildPrompt(text);
      final response = await GemmaEngine.generate(prompt);
      if (response.trim().isEmpty) {
        await _fallback(text);
        return null;
      }
      return response;
    } on GemmaException {
      await _fallback(text);
      return null;
    }
  }

  Future<void> _fallback(String text) async {
    final db = AppDatabase();
    final repo = SyncRepository(db);
    await repo.enqueue(
      type: SyncItemType.gemmaFallback.value,
      payloadJson: jsonEncode({
        'text': text,
        'timestamp': DateTime.now().toIso8601String(),
      }),
      clientId: const Uuid().v4(),
    );
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
  }
}
