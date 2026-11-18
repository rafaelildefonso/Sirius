import 'dart:async';
import 'package:flutter/widgets.dart';

import 'database/database.dart';

/// Makes drift stream queries see rows written by OTHER isolates.
///
/// The notification-action callback, WorkManager tasks and the background
/// services all run in their own isolate, each with its own
/// [AppDatabase.instance] and its own SQLite connection. Drift only
/// invalidates its stream cache for writes made on the *same* isolate, so a
/// task completed from a notification stayed invisible to the home screen
/// until the whole app was restarted (a new process means a fresh cache).
///
/// This watches a cheap change marker and, when it moves, manually dispatches
/// a table update so every active stream re-queries. [refreshNow] forces the
/// re-query regardless of the marker (used on app start/resume).
class CrossIsolateRefresh {
  CrossIsolateRefresh._();

  static const Duration _interval = Duration(seconds: 1);

  static Timer? _timer;
  static String? _lastMarker;
  static final _observer = _RefreshLifecycle();
  static bool _started = false;

  /// Starts the watcher. Idempotent; safe to call from app init.
  static void start() {
    if (_started) return;
    _started = true;
    WidgetsBinding.instance.addObserver(_observer);
    resume();
  }

  static void resume() {
    refreshNow();
    _timer ??= Timer.periodic(_interval, (_) => _check());
  }

  static void pause() {
    _timer?.cancel();
    _timer = null;
  }

  /// Stops the watcher (mainly for tests / hot restart).
  static void stop() {
    pause();
    WidgetsBinding.instance.removeObserver(_observer);
    _started = false;
    _lastMarker = null;
  }

  /// Forces every active drift stream on the task tables to re-read.
  static void refreshNow() {
    final db = AppDatabase();
    db.markTablesUpdated([db.scheduledTasks]);
  }

  /// Cheap change detector: `PRAGMA data_version` only changes when another
  /// connection commits, which is exactly the cross-isolate case. Falls back
  /// to `MAX(updated_at)` when the pragma is unavailable.
  static Future<void> _check() async {
    try {
      final db = AppDatabase();
      final marker = await _readMarker(db);
      if (marker == null) return;
      if (_lastMarker != null && marker != _lastMarker) {
        db.markTablesUpdated([db.scheduledTasks]);
      }
      _lastMarker = marker;
    } catch (e) {
      print('[CrossIsolateRefresh] check failed: $e');
    }
  }

  static Future<String?> _readMarker(AppDatabase db) async {
    try {
      final rows = await db.customSelect('PRAGMA data_version').get();
      if (rows.isNotEmpty && rows.first.data.isNotEmpty) {
        return 'v:${rows.first.data.values.first}';
      }
    } catch (_) {
      // Fall through to the SQL marker below.
    }
    try {
      final rows = await db
          .customSelect('SELECT MAX(updated_at) AS m FROM scheduled_tasks')
          .get();
      if (rows.isNotEmpty) {
        return 'u:${rows.first.data['m']}';
      }
    } catch (e) {
      print('[CrossIsolateRefresh] marker read failed: $e');
    }
    return null;
  }
}

class _RefreshLifecycle with WidgetsBindingObserver {
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      CrossIsolateRefresh.resume();
    } else {
      CrossIsolateRefresh.pause();
    }
  }
}
