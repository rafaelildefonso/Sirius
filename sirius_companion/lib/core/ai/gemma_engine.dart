import 'dart:async';
import 'package:flutter/services.dart';
import '../config/constants.dart';

class GemmaException implements Exception {
  final String code;
  final String message;
  GemmaException(this.code, this.message);

  @override
  String toString() => 'GemmaException($code): $message';
}

class GemmaEngine {
  static const _channel = MethodChannel('sirius/gemma');
  static StreamSubscription? _progressSub;

  static Future<bool> checkHardware() async {
    try {
      final result = await _channel.invokeMethod<bool>('checkHardware');
      return result ?? false;
    } on PlatformException catch (e) {
      throw GemmaException(e.code, e.message ?? 'Unknown error');
    }
  }

  static Future<bool> initialize({bool showProgress = false, void Function(double)? onProgress}) async {
    try {
      if (showProgress && onProgress != null) {
        _channel.setMethodCallHandler((call) async {
          if (call.method == 'downloadProgress') {
            final args = call.arguments as Map;
            final progress = (args['progress'] as num).toDouble();
            onProgress(progress);
          }
          return null;
        });
      }
      final result = await _channel.invokeMethod<bool>('initialize', {'progress': showProgress});
      return result ?? false;
    } on PlatformException catch (e) {
      throw GemmaException(e.code, e.message ?? 'Failed to initialize');
    }
  }

  static Future<bool> downloadWithCookies(String cookies, {String? token, void Function(double)? onProgress}) async {
    try {
      if (onProgress != null) {
        _channel.setMethodCallHandler((call) async {
          if (call.method == 'downloadProgress') {
            final args = call.arguments as Map;
            final progress = (args['progress'] as num).toDouble();
            onProgress(progress);
          }
          return null;
        });
      }
      final result = await _channel.invokeMethod<bool>('downloadWithCookies', {
        'cookies': cookies,
        'url': AppConstants.gemmaDownloadUrl,
        if (token != null && token.isNotEmpty) 'token': token,
      });
      return result ?? false;
    } on PlatformException catch (e) {
      throw GemmaException(e.code, e.message ?? 'Failed to download model');
    }
  }

  static Future<bool> checkModelExists() async {
    try {
      final result = await _channel.invokeMethod<bool>('checkModelExists');
      return result ?? false;
    } on PlatformException catch (e) {
      return false;
    }
  }

  static Future<String> generate(String prompt) async {
    try {
      final result = await _channel.invokeMethod<String>('generate', {'prompt': prompt});
      return result ?? '';
    } on PlatformException catch (e) {
      throw GemmaException(e.code, e.message ?? 'Generation failed');
    }
  }

  static Future<void> shutdown() async {
    try {
      await _channel.invokeMethod<void>('shutdown');
      _channel.setMethodCallHandler(null);
    } on PlatformException catch (e) {
      throw GemmaException(e.code, e.message ?? 'Shutdown failed');
    }
  }
}
