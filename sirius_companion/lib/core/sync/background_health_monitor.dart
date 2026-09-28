import 'dart:async';
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Centralized monitor that keeps the foreground service alive.
///
/// Strategy:
/// 1. Writes a heartbeat timestamp every 30 s from inside the service.
/// 2. A WorkManager periodic task (every 15 min) checks the heartbeat.
///    If the service has not written in > 2 min the task restarts it.
/// 3. The app's main isolate also checks on resume and restarts if needed.
class BackgroundHealthMonitor {
  BackgroundHealthMonitor._();

  static const _heartbeatKey = 'sirius_bg_heartbeat';
  static const Duration _heartbeatInterval = Duration(seconds: 30);
  static const Duration _staleThreshold = Duration(minutes: 2);

  static Timer? _heartbeatTimer;

  // ── Called from inside the background service (onStart) ──────────────

  /// Starts the periodic heartbeat writer. Call once in `onStart()`.
  static void startHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = Timer.periodic(_heartbeatInterval, (_) => _writeHeartbeat());
    _writeHeartbeat();
  }

  static Future<void> _writeHeartbeat() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt(_heartbeatKey, DateTime.now().millisecondsSinceEpoch);
    } catch (_) {}
  }

  /// Mark that the service has stopped (called from onTaskRemoved / stop).
  static Future<void> markStopped() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      // Invalidate the heartbeat so restartIfDead() treats the service as dead.
      await prefs.remove(_heartbeatKey);
    } catch (_) {}
  }

  // ── Called from main isolate or WorkManager health check ─────────────

  /// Returns true if the heartbeat is recent (service is alive).
  static Future<bool> isServiceAlive() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final ts = prefs.getInt(_heartbeatKey);
      if (ts == null) return false;
      final lastHeartbeat = DateTime.fromMillisecondsSinceEpoch(ts);
      return DateTime.now().difference(lastHeartbeat) < _staleThreshold;
    } catch (_) {
      return false;
    }
  }

  /// Force-restarts the foreground service if it is not alive.
  /// Returns true if a restart was performed.
  static Future<bool> restartIfDead() async {
    final alive = await isServiceAlive();
    if (alive) return false;

    print('[HealthMonitor] Service heartbeat stale — restarting');
    try {
      final service = FlutterBackgroundService();
      final isRunning = await service.isRunning();
      if (isRunning) {
        service.invoke('stopService');
        await Future.delayed(const Duration(seconds: 2));
      }
      await service.startService();
      print('[HealthMonitor] Service restarted successfully');
      return true;
    } catch (e) {
      print('[HealthMonitor] Failed to restart service: $e');
      return false;
    }
  }

  /// Cleanup: stop the heartbeat timer.
  static void dispose() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
  }
}
