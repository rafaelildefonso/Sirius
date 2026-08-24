import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/widgets.dart';

import 'sync_worker.dart';

/// Keeps data fresh while the app is open: an inline sync every 45 s while
/// resumed, plus a catch-up whenever connectivity returns. This shrinks the
/// PC→phone latency for newly created tasks from up to ~15 min (WorkManager
/// minimum period) to seconds while the user has the app in the foreground.
class ForegroundSyncService with WidgetsBindingObserver {
  ForegroundSyncService._();

  static final ForegroundSyncService instance = ForegroundSyncService._();

  static const Duration _foregroundInterval = Duration(seconds: 45);

  Timer? _timer;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  bool _started = false;

  void start() {
    if (_started) return;
    _started = true;
    WidgetsBinding.instance.addObserver(this);
    _connectivitySub =
        Connectivity().onConnectivityChanged.listen((results) {
      final online = results.any((r) => r != ConnectivityResult.none);
      if (online) SyncWorker.performSync();
    });
    // Catch-up for anything that arrived while the app was closed.
    SyncWorker.performSync();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.resumed:
        SyncWorker.performSync();
        _timer ??= Timer.periodic(
          _foregroundInterval,
          (_) => SyncWorker.performSync(),
        );
      case AppLifecycleState.paused:
      case AppLifecycleState.detached:
      case AppLifecycleState.hidden:
        _timer?.cancel();
        _timer = null;
      case AppLifecycleState.inactive:
        break;
    }
  }

  void dispose() {
    _timer?.cancel();
    _connectivitySub?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _started = false;
  }
}
