import 'package:flutter/services.dart';

/// Android bridge shared by task reminders and future routine habit calls.
class SimulatedCallService {
  SimulatedCallService._();

  static const MethodChannel _channel = MethodChannel('sirius/simulated_call');

  /// If Android cannot expose the current DND state, keep the flow quiet.
  static Future<bool> isDoNotDisturbActive() async {
    try {
      return await _channel.invokeMethod<bool>('isDoNotDisturbActive') ?? true;
    } catch (_) {
      return true;
    }
  }

  /// Speech starts only in response to an explicit Accept action.
  static Future<void> speakReminder(String text) async {
    await _channel.invokeMethod<void>('speakReminder', {'text': text});
  }

  static Future<void> openDoNotDisturbAccessSettings() async {
    await _channel.invokeMethod<void>('openDoNotDisturbAccessSettings');
  }

  static Future<Map<String, bool>> alertCapabilities() async {
    try {
      final values = await _channel.invokeMapMethod<String, bool>(
        'getAlertCapabilities',
      );
      return values ??
          const {
            'notifications': false,
            'fullScreen': false,
            'exactAlarm': false,
            'dndAccess': false,
          };
    } catch (_) {
      return const {
        'notifications': false,
        'fullScreen': false,
        'exactAlarm': false,
        'dndAccess': false,
      };
    }
  }
}
